from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.config import LoadedConfig
from keeper_factory.goldenset import list_runnable_case_ids, load_original_image, load_target_card
from keeper_factory.judge import JudgeOrchestrator, judge_summary_from_result
from keeper_factory.judge.scoring import category_validation_score
from keeper_factory.ledger import LedgerStore, compute_experiment_signature, format_exp_id, utc_now_iso
from keeper_factory.loop.artifacts import ArtifactUploader
from keeper_factory.loop.p1_render import load_current_p1
from keeper_factory.memory import MemoryStore
from keeper_factory.models.hub import ModelHub
from keeper_factory.schemas import (
    Artifacts,
    CaseCategory,
    EnvInfo,
    ExperimentKind,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentCost,
    KnowledgeDocument,
    KnowledgeType,
    StrategyInfo,
    ValidationState,
    Verdict,
)
from keeper_factory.schemas.enums import KnowledgeStatus, Verdict
from keeper_factory.schemas.judge import JudgeResult
from keeper_factory.util.atomic_io import atomic_write_text
from keeper_factory.util.hashing import sha256_prefix


@dataclass
class ValidationOutcome:
    case_id: str
    exp_id: str
    score: int
    verdict: Verdict | None
    redline_pass: bool
    original_image_url: str | None = None
    result_image_url: str | None = None
    edit_prompt_url: str | None = None
    judge_result_url: str | None = None


@dataclass
class ValidationCampaignResult:
    recipe_id: str
    outcomes: list[ValidationOutcome] = field(default_factory=list)
    total_score: int = 0
    worse_count: int = 0


def select_recipe_for_validation(memory: MemoryStore) -> KnowledgeDocument | None:
    pending = [
        doc
        for doc in memory.list_all(KnowledgeType.CASE_RECIPE)
        if doc.validation_state == ValidationState.PENDING
        and doc.status not in {KnowledgeStatus.DEPRECATED}
    ]
    if not pending:
        return None
    pending.sort(key=lambda doc: (doc.created_loop, doc.id), reverse=True)
    return pending[0]


def pick_validation_cases(
    data_root: Path,
    *,
    category: CaseCategory,
    discovery_case_id: str,
    k: int,
) -> list[str]:
    pool: list[str] = []
    for case_id in list_runnable_case_ids(data_root):
        card = load_target_card(data_root, case_id)
        if card.category != category:
            continue
        if case_id == discovery_case_id:
            continue
        pool.append(case_id)
    if not pool:
        for case_id in list_runnable_case_ids(data_root):
            card = load_target_card(data_root, case_id)
            if card.category == category:
                pool.append(case_id)
    return pool[:k]


def run_validation_campaign(
    *,
    loaded: LoadedConfig,
    hub: ModelHub,
    judge: JudgeOrchestrator,
    ledger: LedgerStore,
    memory: MemoryStore,
    p1_chain,
    uploader: ArtifactUploader,
    state_loop: int,
    state_batch: int,
    recipe: KnowledgeDocument,
    dry_run: bool,
    ledger_root: Path,
    exp_name: str | None = None,
) -> ValidationCampaignResult:
    if not recipe.case_id or not recipe.declared_dimension:
        return ValidationCampaignResult(recipe_id=recipe.id)

    discovery = load_target_card(loaded.data_root, recipe.case_id)
    cases = pick_validation_cases(
        loaded.data_root,
        category=discovery.category,
        discovery_case_id=recipe.case_id,
        k=loaded.config.promotion.min_samples,
    )
    if not cases:
        return ValidationCampaignResult(recipe_id=recipe.id)

    recipe.validation_state = ValidationState.VALIDATING
    recipe.updated_loop = state_loop
    memory.save(recipe)

    p1_version, _, p1_hash = load_current_p1(prompts_dir=loaded.prompts_dir, p1_chain=p1_chain)
    model_labels = hub.env_model_labels()
    out_dir = ledger_root / "experiments" / f"loop_{state_loop:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[ValidationOutcome] = []
    total_score = 0
    worse_count = 0

    for idx, case_id in enumerate(cases, start=1):
        card = load_target_card(loaded.data_root, case_id)
        original = load_original_image(loaded.data_root, case_id)
        exp_id = format_exp_id(loop=state_loop, kind="val", suffix=f"s{idx}")
        strategy_summary = recipe.strategy_summary or "validation replay"
        edit_prompt = (
            f"Improve along {recipe.declared_dimension}.\n"
            f"Strategy: {strategy_summary}"
        )
        if not dry_run:
            hub.reset_cost()
            edit_prompt = hub.generate_text(
                node="f2_edit_prompt",
                user_prompt=edit_prompt,
                images=[original],
            )
        edit_prompt_path = out_dir / f"{exp_id}_edit_prompt.txt"
        atomic_write_text(edit_prompt_path, edit_prompt + "\n")

        if dry_run:
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
        result_sha = uploader.sha256_file(result_image_path)
        original_image_url = uploader.ensure_original_url(case_id)
        oss_scope = f"{exp_name.strip()}/" if exp_name and exp_name.strip() else ""

        if dry_run:
            verdict = Verdict.BETTER if card.category == CaseCategory.BAD else Verdict.SAME
            score = category_validation_score(
                category=card.category,
                redline_pass=True,
                verdict_vs_original=verdict,
            )
            judge_ref = None
            judge_summary = judge_summary_from_result(
                JudgeResult.model_validate(
                    {
                        "case_id": case_id,
                        "candidate_id": exp_id,
                        "judge_meta": {
                            "judge_model": model_labels["judge_model"],
                            "redline_prompt_hash": judge.redline_prompt_hash,
                            "quality_prompt_hash": judge.quality_prompt_hash,
                            "dimension_vocab": judge.dimension_vocab,
                        },
                        "redline": {"pass": True, "violations": []},
                        "direction": {
                            "declared_dimension": recipe.declared_dimension,
                            "hit_target_card": True,
                            "score": 3,
                            "rationale": "dry-run validation",
                        },
                        "execution": {
                            "realization": {"score": 3, "evidence": "dry-run"},
                            "intensity": {"score": 3, "evidence": "dry-run"},
                            "collateral_damage": {"score": 3, "evidence": "dry-run"},
                        },
                        "verdict_vs_original": verdict.value,
                        "pairwise": [],
                        "failure_tags": [],
                        "confidence": "medium",
                    }
                )
            )
        else:
            hub.reset_cost()
            judge_result = judge.judge(
                case_id=case_id,
                candidate_id=exp_id,
                original=original,
                candidate=result_image,
                target_card=card,
                declared_dimension=recipe.declared_dimension,
                opponents=[],
            )
            judge_summary = judge_summary_from_result(judge_result)
            verdict = judge_result.verdict_vs_original
            score = category_validation_score(
                category=card.category,
                redline_pass=judge_result.redline.pass_,
                verdict_vs_original=verdict,
            )
            judge_json_path = out_dir / f"{exp_id}_judge.json"
            judge_ref = uploader.publish_json(
                judge_result.model_dump(mode="json", by_alias=True),
                oss_key=f"experiments/{oss_scope}loop_{state_loop:03d}/{exp_id}_judge.json",
                local_path=judge_json_path,
            )

        oss_prefix = f"experiments/{oss_scope}loop_{state_loop:03d}/{exp_id}"
        prompt_ref = uploader.publish_file(
            edit_prompt_path,
            oss_key=f"{oss_prefix}_edit_prompt.txt",
        )
        image_ref = uploader.publish_file(
            result_image_path,
            oss_key=f"{oss_prefix}_result.png",
        )
        upload_pending = prompt_ref.pending or image_ref.pending or (
            judge_ref.pending if judge_ref is not None else False
        )

        strategy = StrategyInfo(
            p1_version=p1_version,
            candidate_index=idx,
            declared_dimension=recipe.declared_dimension,
            strategy_digest=sha256_prefix(strategy_summary),
            injected_knowledge=[],
            validates_recipe=recipe.id,
        )
        env = EnvInfo(
            vlm=model_labels["vlm"],
            edit_model=model_labels["edit_model"],
            judge_model=model_labels["judge_model"],
            p1_hash=p1_hash,
            redline_prompt_hash=judge.redline_prompt_hash,
            quality_prompt_hash=judge.quality_prompt_hash,
            dimension_vocab=judge.dimension_vocab,
            anchor_set=judge.anchor_set.version,
        )
        exp_sig = compute_experiment_signature(
            case_id=case_id,
            declared_dimension=strategy.declared_dimension,
            strategy_digest=strategy.strategy_digest,
            injected_knowledge=strategy.injected_knowledge,
            env=env,
        )
        cost = hub.consume_cost() or ExperimentCost()
        record = ExperimentRecord(
            exp_id=exp_id,
            exp_sig=exp_sig,
            loop=state_loop,
            batch=state_batch,
            kind=ExperimentKind.VALIDATION,
            case_id=case_id,
            strategy=strategy,
            env=env,
            artifacts=Artifacts(
                original_image_url=original_image_url,
                edit_prompt_url=prompt_ref.url,
                result_image_url=image_ref.url,
                result_image_sha256=result_sha,
                upload_pending=upload_pending,
            ),
            judge_summary=judge_summary,
            judge_result_url=judge_ref.url if judge_ref is not None else None,
            status=ExperimentStatus.COMPLETED,
            cost=cost,
            created_at=utc_now_iso(),
        )
        ledger.write_experiment(record)

        if score < 0:
            worse_count += 1
        total_score += score
        outcomes.append(
            ValidationOutcome(
                case_id=case_id,
                exp_id=exp_id,
                score=score,
                verdict=verdict,
                redline_pass=judge_summary.redline_pass,
                original_image_url=original_image_url,
                result_image_url=image_ref.url,
                edit_prompt_url=prompt_ref.url,
                judge_result_url=judge_ref.url if judge_ref is not None else None,
            )
        )

    recipe.validation_state = ValidationState.RESOLVED
    recipe.updated_loop = state_loop
    memory.save(recipe)

    return ValidationCampaignResult(
        recipe_id=recipe.id,
        outcomes=outcomes,
        total_score=total_score,
        worse_count=worse_count,
    )
