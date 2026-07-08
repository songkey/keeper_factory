from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from keeper_factory.config import LoadedConfig
from keeper_factory.goldenset import list_case_ids, load_original_image, load_target_card
from keeper_factory.judge import JudgeOrchestrator, OpponentCandidate, judge_summary_from_result
from keeper_factory.ledger import (
    LedgerStore,
    P1SlotDiff,
    P1VersionChain,
    P1VersionRecord,
    compute_experiment_signature,
    format_exp_id,
    utc_now_iso,
)
from keeper_factory.memory import MemoryStore, PromotionManager, select_injections
from keeper_factory.models.hub import ModelHub
from keeper_factory.schemas import (
    Artifacts,
    CaseCategory,
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
    LoopStage,
    StrategyInfo,
    ValidationState,
    Verdict,
)
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


def stage_f1(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    memory: MemoryStore,
    p1_chain: P1VersionChain,
) -> LoopState:
    case_id, category = pick_case_for_loop(loaded.data_root, state.loop)
    card = load_target_card(loaded.data_root, case_id)
    original = load_original_image(loaded.data_root, case_id)
    p1_version = p1_chain.ensure_initial(created_loop=0)
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
    prompt = (
        f"T0:\n{t0_text}\n\n"
        f"Current P1 version: {p1_version}\n"
        f"Case: {case_id}\nCategory: {card.category.value}\n"
        f"Generate {loaded.config.loop.candidate_num} diverse candidate strategies.\n"
        "Each candidate must contain declared_dimension and strategy_summary.\n"
        f"Knowledge injections:\n{injection_text or '- (none)'}\n"
    )

    if hub.dry_run:
        candidates = [
            CandidateDraft(
                declared_dimension=(card.candidate_dimensions[i % len(card.candidate_dimensions)].dimension),
                strategy_summary=f"dry-run strategy #{i + 1}",
            )
            for i in range(loaded.config.loop.candidate_num)
        ]
    else:
        result = hub.generate_json(
            node="f1_candidate",
            schema=F1Output,
            user_prompt=prompt,
            images=[original],
        )
        candidates = result.data.candidates
        if not candidates:
            candidates = [CandidateDraft(declared_dimension="other", strategy_summary="fallback strategy")]

    state.case_id = case_id
    state.category = category.value
    state.candidates = [item.model_dump(mode="json") for item in candidates[: loaded.config.loop.candidate_num]]
    state.summary_lines = [
        f"case={case_id}",
        f"category={category.value}",
        f"candidates={len(state.candidates)}",
        f"injections={len(injections.all_ids)}",
    ]
    return state


def stage_f2(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    p1_chain: P1VersionChain,
) -> tuple[LoopState, list[dict[str, Any]]]:
    if not state.case_id:
        raise RuntimeError("F2 requires case_id from F1")

    card = load_target_card(loaded.data_root, state.case_id)
    original = load_original_image(loaded.data_root, state.case_id)
    p1_version = p1_chain.ensure_initial(created_loop=0)
    out_dir = loaded.data_root / "ledger" / "experiments" / f"loop_{state.loop:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    state.candidate_exp_ids = []
    for idx, candidate in enumerate(state.candidates, start=1):
        exp_id = format_exp_id(loop=state.loop, kind="main", suffix=f"c{idx}")
        state.candidate_exp_ids.append(exp_id)
        declared_dimension = str(candidate.get("declared_dimension") or "other")
        strategy_summary = str(candidate.get("strategy_summary") or "")
        edit_prompt = (
            f"Case {state.case_id}: improve along {declared_dimension}.\n"
            f"Strategy: {strategy_summary}\n"
            f"Must keep: {', '.join(card.must_keep)}\n"
            f"Forbidden: {', '.join(card.forbidden)}"
        )
        if not hub.dry_run:
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
            edited = hub.image_edit(
                node="f2_image_edit",
                image=Image.fromarray(original.astype(np.uint8), mode="RGB"),
                prompt=edit_prompt,
            )
            result_image = np.asarray(edited.convert("RGB"), dtype=np.uint8)

        result_image_path = out_dir / f"{exp_id}_result.png"
        Image.fromarray(result_image, mode="RGB").save(result_image_path)
        outputs.append(
            {
                "exp_id": exp_id,
                "declared_dimension": declared_dimension,
                "strategy_summary": strategy_summary,
                "edit_prompt_path": str(edit_prompt_path),
                "result_image_path": str(result_image_path),
                "result_image": result_image,
                "injected_knowledge": [],
                "p1_version": p1_version,
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
) -> tuple[LoopState, list[ExperimentRecord]]:
    if not state.case_id:
        raise RuntimeError("F3 requires case_id from F1")
    card = load_target_card(loaded.data_root, state.case_id)
    original = load_original_image(loaded.data_root, state.case_id)
    model_labels = hub.env_model_labels()

    records: list[ExperimentRecord] = []
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
            judge_result = judge.judge(
                case_id=state.case_id,
                candidate_id=output["exp_id"],
                original=original,
                candidate=output["result_image"],
                target_card=card,
                declared_dimension=output["declared_dimension"],
                opponents=opponents,
            )

        env = EnvInfo(
            vlm=model_labels["vlm"],
            edit_model=model_labels["edit_model"],
            judge_model=model_labels["judge_model"],
            p1_hash=sha256_prefix(output["p1_version"]),
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
        artifacts = Artifacts(
            edit_prompt_url=f"file://{output['edit_prompt_path']}",
            result_image_url=f"file://{output['result_image_path']}",
            result_image_sha256=sha256_hex(Path(output["result_image_path"]).read_bytes()),
        )
        cost = hub.consume_cost()
        record = ExperimentRecord(
            exp_id=output["exp_id"],
            exp_sig=exp_sig,
            loop=state.loop,
            batch=state.batch,
            kind=ExperimentKind.MAIN,
            case_id=state.case_id,
            strategy=strategy,
            env=env,
            artifacts=artifacts,
            judge_summary=judge_summary_from_result(judge_result),
            judge_result_url=None,
            status=ExperimentStatus.COMPLETED,
            cost=cost if cost is not None else ExperimentCost(),
            created_at=utc_now_iso(),
        )
        ledger.write_experiment(record)
        state.records_written.append(record.exp_id)
        records.append(record)

    ranked = sorted(
        records,
        key=lambda rec: (
            0 if rec.judge_summary and rec.judge_summary.verdict_vs_original == Verdict.BETTER else 1,
            0 if rec.judge_summary and rec.judge_summary.verdict_vs_original == Verdict.SAME else 1,
            -(rec.judge_summary.direction_score if rec.judge_summary else 0),
        ),
    )
    if ranked:
        top = ranked[0]
        state.top_candidate_id = top.exp_id
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
            case_id=top.case_id,
            declared_dimension=top.strategy.declared_dimension,
            strategy_summary=f"Top recipe from {top.exp_id}",
            p1_variant_ref=top.strategy.p1_version,
            judge_result_ref=top.exp_sig,
            validation_state=ValidationState.PENDING,
            ttl_loops=loaded.config.memory.case_recipe_ttl,
        )
        memory.save(recipe)
        state.top_recipe_id = recipe.id
    return state, records


def stage_f4a(*, state: LoopState, memory: MemoryStore) -> LoopState:
    if not state.top_recipe_id:
        return state
    recipe = memory.get(state.top_recipe_id)
    if recipe is None:
        return state
    recipe.validation_state = ValidationState.VALIDATING
    recipe.updated_loop = state.loop
    memory.save(recipe)
    recipe.validation_state = ValidationState.RESOLVED
    recipe.updated_loop = state.loop
    memory.save(recipe)
    return state


def stage_f4b(*, state: LoopState, memory: MemoryStore) -> LoopState:
    manager = PromotionManager(memory)
    manager.discard_expired_case_recipes(current_loop=state.loop)
    return state


def stage_f4c(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    state: LoopState,
    p1_chain: P1VersionChain,
) -> LoopState:
    current = p1_chain.ensure_initial(created_loop=0)
    prompt = (
        "Refine P.1 minimally based on latest loop evidence.\n"
        f"Loop={state.loop}, top_candidate={state.top_candidate_id}\n"
        f"Summary lines:\n" + "\n".join(state.summary_lines)
    )
    if hub.dry_run:
        refine_text = "dry-run refine: tighten constraints wording"
    else:
        refine_text = hub.generate_text(node="f4_refine", user_prompt=prompt)
    current_num = int(current.split("_v")[-1]) if "_v" in current else 1
    next_version = f"p1_v{current_num + 1:03d}"
    diff = P1SlotDiff(
        slot="constraints",
        before_hash=sha256_prefix(current),
        after_hash=sha256_prefix(next_version + refine_text),
        diff_text=refine_text[:500],
    )
    record = P1VersionRecord(
        version=next_version,
        parent=current,
        created_loop=state.loop,
        slot_diffs=[diff],
        rationale="loop refine",
        refine_exp_ref=state.top_candidate_id,
    )
    p1_chain.write_version(record)
    p1_chain.set_current_version(next_version)
    return state


def stage_f5(*, loaded: LoadedConfig, state: LoopState) -> LoopState:
    report_dir = loaded.data_root / "ledger" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"loop_{state.loop:03d}.md"
    lines = [
        f"# Loop {state.loop}",
        "",
        f"- Batch: {state.batch}",
        f"- Case: {state.case_id}",
        f"- Category: {state.category}",
        f"- Top candidate: {state.top_candidate_id}",
        f"- Top recipe: {state.top_recipe_id}",
        "",
        "## Short summary",
    ] + [f"- {item}" for item in state.summary_lines]
    atomic_write_text(report_path, "\n".join(lines) + "\n")
    state.report_path = str(report_path)
    return state


def stage_batch_wait(
    *,
    loaded: LoadedConfig,
    state: LoopState,
    memory: MemoryStore,
) -> LoopState:
    if state.batch <= 0:
        return state
    # Batch boundary: move candidate knowledge to pending review.
    if state.loop % loaded.config.loop.batch_size == 0:
        manager = PromotionManager(memory)
        ids = [
            item.id
            for item in memory.list_all()
            if item.status == KnowledgeStatus.CANDIDATE
        ]
        manager.mark_pending_review(ids, loop=state.loop)
    return state

