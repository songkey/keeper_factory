from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from pydantic import BaseModel, Field

from keeper_factory.config import LoadedConfig
from keeper_factory.goldenset import list_case_ids, load_original_image, load_target_card
from keeper_factory.judge import JudgeOrchestrator, OpponentCandidate, judge_summary_from_result
from keeper_factory.judge.scoring import category_validation_score
from keeper_factory.judge.vocab import format_vocab_for_prompt, is_valid_dimension
from keeper_factory.ledger import (
    LedgerStore,
    P1SlotDiff,
    P1VersionChain,
    P1VersionRecord,
    compute_experiment_signature,
    format_exp_id,
    utc_now_iso,
)
from keeper_factory.loop.artifacts import ArtifactUploader
from keeper_factory.loop.context import load_recent_loop_summaries
from keeper_factory.loop.p1_render import load_current_p1, render_p1_text, slots_from_record
from keeper_factory.loop.ranking import rank_records
from keeper_factory.loop.report import build_loop_report
from keeper_factory.loop.checkpoint import CheckpointStore
from keeper_factory.loop.synthesis import SynthesisResult, synthesize_from_validation
from keeper_factory.loop.validation import (
    ValidationCampaignResult,
    run_validation_campaign,
    select_recipe_for_validation,
)
from keeper_factory.mail import MailChannel, write_batch_pending_file
from keeper_factory.memory import MemoryStore, PromotionManager, select_injections
from keeper_factory.models.hub import ModelHub
from keeper_factory.schemas import (
    Artifacts,
    CaseCategory,
    Confidence,
    EnvInfo,
    ExperimentKind,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentCost,
    JudgeResult,
    KnowledgeDocument,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeType,
    StrategyInfo,
    ValidationState,
    Verdict,
)
from keeper_factory.schemas.knowledge import KnowledgeLineage
from keeper_factory.util.atomic_io import atomic_write_json, atomic_write_text
from keeper_factory.util.hashing import sha256_hex, sha256_prefix

CATEGORY_ROTATION: tuple[CaseCategory, ...] = (
    CaseCategory.BAD,
    CaseCategory.BAD,
    CaseCategory.GOOD,
    CaseCategory.REDLINE,
)


class CandidateDraft(BaseModel):
    declared_dimension: str
    strategy_summary: str


class F1Output(BaseModel):
    candidates: list[CandidateDraft] = Field(default_factory=list)


@dataclass
class LoopState:
    loop: int
    batch: int
    stage_history: list[str] = field(default_factory=list)
    case_id: str | None = None
    category: str | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)
    candidate_exp_ids: list[str] = field(default_factory=list)
    records_written: list[str] = field(default_factory=list)
    top_candidate_id: str | None = None
    top_recipe_id: str | None = None
    report_path: str | None = None
    summary_lines: list[str] = field(default_factory=list)
    injected_knowledge: list[str] = field(default_factory=list)
    dnr_skipped: int = 0
    main_score: int | None = None
    validation_recipe_id: str | None = None
    knowledge_changes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "loop": self.loop,
            "batch": self.batch,
            "stage_history": self.stage_history,
            "case_id": self.case_id,
            "category": self.category,
            "candidates": self.candidates,
            "candidate_exp_ids": self.candidate_exp_ids,
            "records_written": self.records_written,
            "top_candidate_id": self.top_candidate_id,
            "top_recipe_id": self.top_recipe_id,
            "report_path": self.report_path,
            "summary_lines": self.summary_lines,
            "injected_knowledge": self.injected_knowledge,
            "dnr_skipped": self.dnr_skipped,
            "main_score": self.main_score,
            "validation_recipe_id": self.validation_recipe_id,
            "knowledge_changes": self.knowledge_changes,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> LoopState:
        return cls(
            loop=int(payload.get("loop", 0)),
            batch=int(payload.get("batch", 0)),
            stage_history=list(payload.get("stage_history", [])),
            case_id=payload.get("case_id"),
            category=payload.get("category"),
            candidates=list(payload.get("candidates", [])),
            candidate_exp_ids=list(payload.get("candidate_exp_ids", [])),
            records_written=list(payload.get("records_written", [])),
            top_candidate_id=payload.get("top_candidate_id"),
            top_recipe_id=payload.get("top_recipe_id"),
            report_path=payload.get("report_path"),
            summary_lines=list(payload.get("summary_lines", [])),
            injected_knowledge=list(payload.get("injected_knowledge", [])),
            dnr_skipped=int(payload.get("dnr_skipped", 0)),
            main_score=payload.get("main_score"),
            validation_recipe_id=payload.get("validation_recipe_id"),
            knowledge_changes=list(payload.get("knowledge_changes", [])),
        )


def pick_case_for_loop(data_root: Path, loop_no: int) -> tuple[str, CaseCategory]:
    case_ids = list_case_ids(data_root)
    if not case_ids:
        raise RuntimeError("goldenset is empty; add at least one case before running loops")

    wanted = CATEGORY_ROTATION[(loop_no - 1) % len(CATEGORY_ROTATION)]
    by_category: dict[CaseCategory, list[str]] = {c: [] for c in CaseCategory}
    for case_id in case_ids:
        card = load_target_card(data_root, case_id)
        by_category[card.category].append(case_id)

    selected_pool = by_category[wanted] or case_ids
    index = (loop_no - 1) % len(selected_pool)
    selected = selected_pool[index]
    card = load_target_card(data_root, selected)
    return selected, card.category


def _normalize_dimension(dimension: str) -> str:
    return dimension if is_valid_dimension(dimension) else "other"


def _filter_dnr_candidates(
    *,
    candidates: list[CandidateDraft],
    ledger: LedgerStore,
    case_id: str,
    p1_hash: str,
    injected_knowledge: list[str],
    env_template: EnvInfo,
) -> tuple[list[CandidateDraft], int]:
    kept: list[CandidateDraft] = []
    skipped = 0
    for item in candidates:
        strategy_digest = sha256_prefix(item.strategy_summary)
        env = env_template.model_copy(update={"p1_hash": p1_hash})
        sig = compute_experiment_signature(
            case_id=case_id,
            declared_dimension=_normalize_dimension(item.declared_dimension),
            strategy_digest=strategy_digest,
            injected_knowledge=injected_knowledge,
            env=env,
        )
        if ledger.is_dnr(sig):
            skipped += 1
            continue
        kept.append(
            CandidateDraft(
                declared_dimension=_normalize_dimension(item.declared_dimension),
                strategy_summary=item.strategy_summary,
            )
        )
    return kept, skipped


def stage_f1(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    memory: MemoryStore,
    p1_chain: P1VersionChain,
    ledger: LedgerStore,
) -> LoopState:
    case_id, category = pick_case_for_loop(loaded.data_root, state.loop)
    card = load_target_card(loaded.data_root, case_id)
    original = load_original_image(loaded.data_root, case_id)
    p1_version, slots, p1_hash = load_current_p1(prompts_dir=loaded.prompts_dir, p1_chain=p1_chain)
    p1_text = render_p1_text(prompts_dir=loaded.prompts_dir, slots=slots)
    t0_text = (loaded.prompts_dir / "t0.txt").read_text(encoding="utf-8").strip()
    injections = select_injections(
        memory.list_all(),
        dimensions=[item.dimension for item in card.candidate_dimensions],
        category=card.category,
        image_class=card.scene_brief,
        max_scoped=loaded.config.memory.max_injection_num,
    )
    injection_text = "\n".join(
        [f"- {item.text}" for item in (*injections.failure_notes, *injections.scoped_items)]
    )
    context_lines = load_recent_loop_summaries(
        loaded.data_root / "ledger" / "loops",
        current_loop=state.loop,
        context_window=loaded.config.loop.context_window,
    )
    prompt = (
        f"T0:\n{t0_text}\n\n"
        f"Current P.1 ({p1_version}):\n{p1_text}\n\n"
        f"Case: {case_id}\nCategory: {card.category.value}\n"
        f"Generate {loaded.config.loop.candidate_num} diverse candidate strategies.\n"
        "Each candidate must use declared_dimension from this closed vocabulary:\n"
        f"{format_vocab_for_prompt()}\n"
        "Each candidate must contain declared_dimension and strategy_summary.\n"
        f"Recent loop context:\n{chr(10).join(context_lines) if context_lines else '- (none)'}\n"
        f"Knowledge injections:\n{injection_text or '- (none)'}\n"
    )

    model_labels = hub.env_model_labels()
    env_template = EnvInfo(
        vlm=model_labels["vlm"],
        edit_model=model_labels["edit_model"],
        judge_model=model_labels["judge_model"],
        p1_hash=p1_hash,
        redline_prompt_hash="pending",
        quality_prompt_hash="pending",
        dimension_vocab="dimension_vocab_v0",
        anchor_set="anchor_v0",
    )

    if hub.dry_run:
        candidates = [
            CandidateDraft(
                declared_dimension=card.candidate_dimensions[i % len(card.candidate_dimensions)].dimension,
                strategy_summary=f"dry-run strategy #{i + 1}",
            )
            for i in range(loaded.config.loop.candidate_num)
        ]
    else:
        hub.reset_cost()
        result = hub.generate_json(
            node="f1_candidate",
            schema=F1Output,
            user_prompt=prompt,
            images=[original],
        )
        candidates = result.data.candidates
        if not candidates:
            candidates = [CandidateDraft(declared_dimension="other", strategy_summary="fallback strategy")]

        filtered, skipped = _filter_dnr_candidates(
            candidates=candidates,
            ledger=ledger,
            case_id=case_id,
            p1_hash=p1_hash,
            injected_knowledge=injections.all_ids,
            env_template=env_template,
        )
        state.dnr_skipped = skipped
        if skipped and len(filtered) < loaded.config.loop.candidate_num:
            refill_prompt = (
                prompt
                + f"\nAvoid repeating prior low-value signatures. Generate "
                f"{loaded.config.loop.candidate_num - len(filtered)} replacement candidates.\n"
            )
            hub.reset_cost()
            refill = hub.generate_json(
                node="f1_candidate",
                schema=F1Output,
                user_prompt=refill_prompt,
                images=[original],
            )
            more, more_skipped = _filter_dnr_candidates(
                candidates=refill.data.candidates,
                ledger=ledger,
                case_id=case_id,
                p1_hash=p1_hash,
                injected_knowledge=injections.all_ids,
                env_template=env_template,
            )
            state.dnr_skipped += more_skipped
            filtered.extend(more)
        candidates = filtered[: loaded.config.loop.candidate_num]
        if not candidates:
            candidates = [CandidateDraft(declared_dimension="other", strategy_summary="fallback strategy")]

    state.case_id = case_id
    state.category = category.value
    state.injected_knowledge = injections.all_ids
    state.candidates = [
        CandidateDraft(
            declared_dimension=_normalize_dimension(item.declared_dimension),
            strategy_summary=item.strategy_summary,
        ).model_dump(mode="json")
        for item in candidates[: loaded.config.loop.candidate_num]
    ]
    state.summary_lines = [
        f"case={case_id}",
        f"category={category.value}",
        f"candidates={len(state.candidates)}",
        f"injections={len(injections.all_ids)}",
        f"p1={p1_version}",
    ]
    return state


def stage_f2(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    p1_chain: P1VersionChain,
    uploader: ArtifactUploader,
) -> tuple[LoopState, list[dict[str, Any]]]:
    if not state.case_id:
        raise RuntimeError("F2 requires case_id from F1")

    original = load_original_image(loaded.data_root, state.case_id)
    p1_version, _, p1_hash = load_current_p1(prompts_dir=loaded.prompts_dir, p1_chain=p1_chain)
    out_dir = loaded.data_root / "ledger" / "experiments" / f"loop_{state.loop:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    state.candidate_exp_ids = []
    for idx, candidate in enumerate(state.candidates, start=1):
        exp_id = format_exp_id(loop=state.loop, kind="main", suffix=f"c{idx}")
        state.candidate_exp_ids.append(exp_id)
        declared_dimension = _normalize_dimension(str(candidate.get("declared_dimension") or "other"))
        strategy_summary = str(candidate.get("strategy_summary") or "")
        edit_prompt = (
            f"Improve the image along dimension '{declared_dimension}'.\n"
            f"Strategy: {strategy_summary}"
        )
        if not hub.dry_run:
            hub.reset_cost()
            edit_prompt = hub.generate_text(
                node="f2_edit_prompt",
                user_prompt=edit_prompt,
                images=[original],
            )
        edit_prompt_path = out_dir / f"{exp_id}_edit_prompt.txt"
        atomic_write_text(edit_prompt_path, edit_prompt + "\n")

        if hub.dry_run:
            result_image = original
        else:
            hub.reset_cost()
            edited = hub.image_edit(
                node="f2_image_edit",
                image=Image.fromarray(original.astype(np.uint8), mode="RGB"),
                prompt=edit_prompt,
            )
            result_image = np.asarray(edited.convert("RGB"), dtype=np.uint8)

        result_image_path = out_dir / f"{exp_id}_result.png"
        Image.fromarray(result_image, mode="RGB").save(result_image_path)
        oss_prefix = f"experiments/loop_{state.loop:03d}/{exp_id}"
        outputs.append(
            {
                "exp_id": exp_id,
                "declared_dimension": declared_dimension,
                "strategy_summary": strategy_summary,
                "edit_prompt_path": str(edit_prompt_path),
                "result_image_path": str(result_image_path),
                "edit_prompt_url": uploader.url_for_file(
                    edit_prompt_path,
                    oss_key=f"{oss_prefix}_edit_prompt.txt",
                ),
                "result_image_url": uploader.url_for_file(
                    result_image_path,
                    oss_key=f"{oss_prefix}_result.png",
                ),
                "result_image": result_image,
                "injected_knowledge": list(state.injected_knowledge),
                "p1_version": p1_version,
                "p1_hash": p1_hash,
            }
        )
    return state, outputs


def stage_f3(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    ledger: LedgerStore,
    memory: MemoryStore,
    judge: JudgeOrchestrator,
    f2_outputs: list[dict[str, Any]],
    uploader: ArtifactUploader,
) -> tuple[LoopState, list[ExperimentRecord]]:
    if not state.case_id or not state.category:
        raise RuntimeError("F3 requires case_id and category from F1")
    card = load_target_card(loaded.data_root, state.case_id)
    category = CaseCategory(state.category)
    original = load_original_image(loaded.data_root, state.case_id)
    model_labels = hub.env_model_labels()
    out_dir = loaded.data_root / "ledger" / "experiments" / f"loop_{state.loop:03d}"

    records: list[ExperimentRecord] = []
    judge_results: dict[str, JudgeResult] = {}

    for i, output in enumerate(f2_outputs):
        opponents = [
            OpponentCandidate(candidate_id=other["exp_id"], image=other["result_image"])
            for j, other in enumerate(f2_outputs)
            if i != j
        ]
        if hub.dry_run:
            verdict = Verdict.BETTER if i == 0 else Verdict.SAME
            judge_result = JudgeResult.model_validate(
                {
                    "case_id": state.case_id,
                    "candidate_id": output["exp_id"],
                    "judge_meta": {
                        "judge_model": model_labels["judge_model"],
                        "redline_prompt_hash": judge.redline_prompt_hash,
                        "quality_prompt_hash": judge.quality_prompt_hash,
                        "dimension_vocab": judge.dimension_vocab,
                    },
                    "redline": {"pass": True, "violations": []},
                    "direction": {
                        "declared_dimension": output["declared_dimension"],
                        "hit_target_card": True,
                        "score": 3 if i == 0 else 2,
                        "rationale": "dry-run",
                    },
                    "execution": {
                        "realization": {"score": 3, "evidence": "dry-run"},
                        "intensity": {"score": 2, "evidence": "dry-run"},
                        "collateral_damage": {"score": 3, "evidence": "dry-run"},
                    },
                    "verdict_vs_original": verdict.value,
                    "pairwise": [],
                    "failure_tags": [],
                    "confidence": "medium",
                }
            )
        else:
            hub.reset_cost()
            judge_result = judge.judge(
                case_id=state.case_id,
                candidate_id=output["exp_id"],
                original=original,
                candidate=output["result_image"],
                target_card=card,
                declared_dimension=output["declared_dimension"],
                opponents=opponents,
            )

        judge_results[output["exp_id"]] = judge_result
        judge_json_path = out_dir / f"{output['exp_id']}_judge.json"
        judge_result_url = uploader.url_for_json(
            judge_result.model_dump(mode="json", by_alias=True),
            oss_key=f"experiments/loop_{state.loop:03d}/{output['exp_id']}_judge.json",
            local_path=judge_json_path,
        )

        env = EnvInfo(
            vlm=model_labels["vlm"],
            edit_model=model_labels["edit_model"],
            judge_model=model_labels["judge_model"],
            p1_hash=output["p1_hash"],
            redline_prompt_hash=judge_result.judge_meta.redline_prompt_hash,
            quality_prompt_hash=judge_result.judge_meta.quality_prompt_hash,
            dimension_vocab=judge_result.judge_meta.dimension_vocab,
            anchor_set=judge.anchor_set.version,
        )
        strategy = StrategyInfo(
            p1_version=output["p1_version"],
            candidate_index=int(output["exp_id"].split("c")[-1]),
            declared_dimension=output["declared_dimension"],
            strategy_digest=sha256_prefix(output["strategy_summary"]),
            injected_knowledge=list(output["injected_knowledge"]),
        )
        exp_sig = compute_experiment_signature(
            case_id=state.case_id,
            declared_dimension=strategy.declared_dimension,
            strategy_digest=strategy.strategy_digest,
            injected_knowledge=strategy.injected_knowledge,
            env=env,
        )
        cost = hub.consume_cost() or ExperimentCost()
        record = ExperimentRecord(
            exp_id=output["exp_id"],
            exp_sig=exp_sig,
            loop=state.loop,
            batch=state.batch,
            kind=ExperimentKind.MAIN,
            case_id=state.case_id,
            strategy=strategy,
            env=env,
            artifacts=Artifacts(
                edit_prompt_url=output["edit_prompt_url"],
                result_image_url=output["result_image_url"],
                result_image_sha256=uploader.sha256_file(Path(output["result_image_path"])),
            ),
            judge_summary=judge_summary_from_result(judge_result),
            judge_result_url=judge_result_url,
            status=ExperimentStatus.COMPLETED,
            cost=cost,
            created_at=utc_now_iso(),
        )
        ledger.write_experiment(record)
        state.records_written.append(record.exp_id)
        records.append(record)

    ranked = rank_records(records, category=category, judge_results=judge_results)
    if ranked:
        top = ranked[0]
        top_result = judge_results[top.exp_id]
        state.top_candidate_id = top.exp_id
        state.main_score = category_validation_score(
            category=category,
            redline_pass=top_result.redline.pass_,
            verdict_vs_original=top_result.verdict_vs_original,
        )
        recipe_id = memory.allocate_id(KnowledgeType.CASE_RECIPE)
        recipe = KnowledgeDocument(
            id=recipe_id,
            type=KnowledgeType.CASE_RECIPE,
            status=KnowledgeStatus.CANDIDATE,
            created_loop=state.loop,
            updated_loop=state.loop,
            scope=KnowledgeScope(
                dimensions=[top.strategy.declared_dimension],
                categories=[card.category],
                image_class=card.scene_brief,
            ),
            confidence=Confidence.LOW,
            evidence=[top.exp_sig],
            lineage=KnowledgeLineage(derived_from=top.exp_id),
            case_id=top.case_id,
            declared_dimension=top.strategy.declared_dimension,
            strategy_summary=next(
                (item["strategy_summary"] for item in f2_outputs if item["exp_id"] == top.exp_id),
                f"Top recipe from {top.exp_id}",
            ),
            p1_variant_ref=top.strategy.p1_version,
            judge_result_ref=top.exp_sig,
            validation_state=ValidationState.PENDING,
            ttl_loops=loaded.config.memory.case_recipe_ttl,
        )
        memory.save(recipe)
        state.top_recipe_id = recipe.id
    return state, records


def stage_f4a(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    memory: MemoryStore,
    ledger: LedgerStore,
    judge: JudgeOrchestrator,
    p1_chain: P1VersionChain,
    uploader: ArtifactUploader,
    dry_run: bool,
) -> tuple[LoopState, ValidationCampaignResult | None]:
    recipe = select_recipe_for_validation(memory)
    if recipe is None and state.top_recipe_id:
        recipe = memory.get(state.top_recipe_id)
    if recipe is None:
        return state, None

    state.validation_recipe_id = recipe.id
    campaign = run_validation_campaign(
        loaded=loaded,
        hub=hub,
        judge=judge,
        ledger=ledger,
        memory=memory,
        p1_chain=p1_chain,
        uploader=uploader,
        state_loop=state.loop,
        state_batch=state.batch,
        recipe=recipe,
        dry_run=dry_run,
    )
    return state, campaign


def stage_f4b(
    *,
    loaded: LoadedConfig,
    state: LoopState,
    memory: MemoryStore,
    campaign: ValidationCampaignResult | None,
    dry_run: bool,
) -> tuple[LoopState, SynthesisResult]:
    synthesis = synthesize_from_validation(
        loaded=loaded,
        memory=memory,
        campaign=campaign,
        loop=state.loop,
        dry_run=dry_run,
    )
    changes: list[str] = []
    if synthesis.promoted_ids:
        changes.append(f"promoted={','.join(synthesis.promoted_ids)}")
    if synthesis.failure_note_ids:
        changes.append(f"failure_notes={','.join(synthesis.failure_note_ids)}")
    if synthesis.discarded_recipe_ids:
        changes.append(f"discarded={','.join(synthesis.discarded_recipe_ids)}")
    state.knowledge_changes = changes
    return state, synthesis


def stage_f4c(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    p1_chain: P1VersionChain,
) -> LoopState:
    current = p1_chain.ensure_initial(created_loop=0)
    current_record = p1_chain.read_version(current)
    if current_record is None:
        raise RuntimeError(f"missing P.1 version: {current}")
    slots = slots_from_record(current_record)
    env = Environment(
        loader=FileSystemLoader(str(loaded.prompts_dir)),
        autoescape=select_autoescape(default_for_string=False, default=False),
    )
    refine_template = env.get_template("p4_refine.jinja")
    refine_prompt = refine_template.render(
        loop=state.loop,
        top_candidate=state.top_candidate_id,
        summary_lines=state.summary_lines,
        current_p1=render_p1_text(prompts_dir=loaded.prompts_dir, slots=slots),
    )
    if hub.dry_run:
        refine_text = slots["constraints"] + "\n(dry-run refine: tighten constraints wording)"
    else:
        hub.reset_cost()
        refine_text = hub.generate_text(node="f4_refine", user_prompt=refine_prompt)

    next_slots = dict(slots)
    next_slots["constraints"] = refine_text.strip()
    before_hash = sha256_prefix(render_p1_text(prompts_dir=loaded.prompts_dir, slots=slots))
    after_hash = sha256_prefix(render_p1_text(prompts_dir=loaded.prompts_dir, slots=next_slots))

    current_num = int(current.split("_v")[-1]) if "_v" in current else 1
    next_version = f"p1_v{current_num + 1:03d}"
    diff = P1SlotDiff(
        slot="constraints",
        before_hash=before_hash,
        after_hash=after_hash,
        diff_text=refine_text[:500],
    )
    record = P1VersionRecord(
        version=next_version,
        parent=current,
        created_loop=state.loop,
        slot_diffs=[diff],
        rationale="loop refine",
        refine_exp_ref=state.top_candidate_id,
        constraints=next_slots["constraints"],
        capabilities=next_slots["capabilities"],
        patterns=next_slots["patterns"],
    )
    p1_chain.write_version(record)
    p1_chain.set_current_version(next_version)
    return state


def stage_f5(
    *,
    loaded: LoadedConfig,
    state: LoopState,
    records: list[ExperimentRecord],
    validation: ValidationCampaignResult | None,
    synthesis: SynthesisResult | None,
    mail: MailChannel | None = None,
) -> LoopState:
    report_dir = loaded.data_root / "ledger" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"loop_{state.loop:03d}.md"
    body, short_summary, main_score = build_loop_report(
        state=state,
        records=records,
        validation=validation,
        synthesis=synthesis,
        loops_root=loaded.data_root / "ledger" / "loops",
        stagnation_threshold=loaded.config.loop.stagnation_threshold,
        dnr_skipped=state.dnr_skipped,
    )
    atomic_write_text(report_path, body)
    state.report_path = str(report_path)
    state.summary_lines = short_summary
    if main_score is not None:
        state.main_score = main_score

    # Informational loop report (non-blocking).
    if mail is not None and mail.enabled:
        result = mail.send_text_detailed(
            subject=f"[KF][loop {state.loop:03d}] Report",
            body=body,
        )
        state.summary_lines.append(result.as_summary())
    elif mail is not None:
        state.summary_lines.append("mail_sent=False reason=disabled")
    return state


def stage_batch_wait(
    *,
    loaded: LoadedConfig,
    state: LoopState,
    memory: MemoryStore,
    store: CheckpointStore,
    mail: MailChannel | None = None,
) -> LoopState:
    if state.batch <= 0:
        return state
    if state.loop % loaded.config.loop.batch_size != 0:
        return state

    manager = PromotionManager(memory)
    # Include already-pending items so resume/re-entry does not wipe the batch list.
    reviewable = [
        item
        for item in memory.list_all()
        if item.status in {KnowledgeStatus.CANDIDATE, KnowledgeStatus.PENDING_REVIEW}
    ]
    candidate_ids = [item.id for item in reviewable if item.status == KnowledgeStatus.CANDIDATE]
    manager.mark_pending_review(candidate_ids, loop=state.loop)

    pending_items = [
        {
            "index": idx,
            "knowledge_id": item.id,
            "type": item.type.value,
        }
        for idx, item in enumerate(sorted(reviewable, key=lambda doc: doc.id), start=1)
    ]
    batch_path = write_batch_pending_file(
        loaded.data_root,
        batch=state.batch,
        loop_end=state.loop,
        pending_items=pending_items,
    )
    store.set_awaiting_approval(batch=state.batch, loop=state.loop)

    report_text = ""
    if state.report_path and Path(state.report_path).is_file():
        report_text = Path(state.report_path).read_text(encoding="utf-8")
    body = (
        f"Batch {state.batch} ended at loop {state.loop}.\n"
        f"Pending review items: {len(pending_items)}\n\n"
        f"{report_text}\n"
        "Reply with lines like `1 ok` or `pp_0001: approve`.\n"
        "Use `kf approve` locally if mail is unavailable.\n"
    )
    if mail is not None and mail.enabled:
        result = mail.send_text_detailed(
            subject=f"[KF][batch {state.batch:03d}] pending approval",
            body=body,
        )
        state.summary_lines.append(result.as_summary())
    elif mail is not None:
        state.summary_lines.append("mail_sent=False reason=disabled")
    else:
        state.summary_lines.append("mail_sent=False reason=no_mail_channel")
    state.summary_lines.append(f"batch_pending={batch_path.name}")
    return state
