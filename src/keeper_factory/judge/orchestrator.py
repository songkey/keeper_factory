from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from keeper_factory.judge.anchors import AnchorSet, load_anchor_set
from keeper_factory.judge.pairwise import PairwiseAgreement, reconcile_bidirectional
from keeper_factory.judge.prompts import render_pairwise_prompt, render_quality_prompt, render_redline_prompt
from keeper_factory.judge.vocab import DIMENSION_VOCAB_VERSION
from keeper_factory.models.hub import ModelHub
from keeper_factory.schemas.enums import Confidence, Verdict
from keeper_factory.schemas.judge import (
    DirectionResult,
    ExecutionDimension,
    ExecutionResult,
    JudgeMeta,
    JudgeResult,
    PairwiseCallOutput,
    PairwiseResult,
    QualityCallOutput,
    RedlineResult,
)
from keeper_factory.schemas.target_card import TargetCard
from keeper_factory.util.hashing import sha256_prefix


@dataclass(frozen=True)
class OpponentCandidate:
    candidate_id: str
    image: np.ndarray


@dataclass
class JudgeOrchestrator:
    hub: ModelHub
    prompts_dir: Path
    anchor_set: AnchorSet
    redline_prompt_hash: str
    quality_prompt_hash: str
    dimension_vocab: str = DIMENSION_VOCAB_VERSION

    @classmethod
    def from_hub(
        cls,
        hub: ModelHub,
        *,
        anchor_set: AnchorSet | None = None,
        anchor_version: str = "anchor_v0",
    ) -> JudgeOrchestrator:
        prompts_dir = hub.loaded.prompts_dir
        if anchor_set is None:
            anchor_set = load_anchor_set(hub.loaded.data_root, version=anchor_version)
        return cls(
            hub=hub,
            prompts_dir=prompts_dir,
            anchor_set=anchor_set,
            redline_prompt_hash=_prompt_hash(prompts_dir / "p3_eval_redline.jinja"),
            quality_prompt_hash=_prompt_hash(prompts_dir / "p3_eval_quality.jinja"),
        )

    def judge(
        self,
        *,
        case_id: str,
        candidate_id: str,
        original: np.ndarray,
        candidate: np.ndarray,
        target_card: TargetCard,
        declared_dimension: str,
        opponents: list[OpponentCandidate] | None = None,
    ) -> JudgeResult:
        judge_model = self.hub.resolve_node("judge_quality").model_name
        meta = JudgeMeta(
            judge_model=judge_model,
            redline_prompt_hash=self.redline_prompt_hash,
            quality_prompt_hash=self.quality_prompt_hash,
            dimension_vocab=self.dimension_vocab,
        )

        redline_prompt = render_redline_prompt(
            prompts_dir=self.prompts_dir,
            target_card=target_card,
            declared_dimension=declared_dimension,
            anchor_set=self.anchor_set,
        )
        redline = self.hub.generate_json(
            node="judge_redline",
            schema=RedlineResult,
            user_prompt=redline_prompt,
            images=[original, candidate],
        ).data

        if not redline.pass_:
            return self._failed_redline_result(
                case_id=case_id,
                candidate_id=candidate_id,
                meta=meta,
                redline=redline,
                declared_dimension=declared_dimension,
            )

        quality_prompt = render_quality_prompt(
            prompts_dir=self.prompts_dir,
            target_card=target_card,
            declared_dimension=declared_dimension,
            anchor_set=self.anchor_set,
        )
        quality = self.hub.generate_json(
            node="judge_quality",
            schema=QualityCallOutput,
            user_prompt=quality_prompt,
            images=[original, candidate],
        ).data

        vs_original = self._pairwise(
            left=candidate,
            right=original,
            left_label=f"candidate:{candidate_id}",
            right_label="original",
            target_card=target_card,
            declared_dimension=declared_dimension,
        )

        pairwise_results: list[PairwiseResult] = [
            PairwiseResult(
                against="original",
                result=vs_original.result,
                bidirectional_agreed=vs_original.bidirectional_agreed,
            )
        ]

        for opponent in opponents or []:
            agreement = self._pairwise(
                left=candidate,
                right=opponent.image,
                left_label=f"candidate:{candidate_id}",
                right_label=f"candidate:{opponent.candidate_id}",
                target_card=target_card,
                declared_dimension=declared_dimension,
            )
            pairwise_results.append(
                PairwiseResult(
                    against=opponent.candidate_id,
                    result=agreement.result,
                    bidirectional_agreed=agreement.bidirectional_agreed,
                )
            )

        return JudgeResult(
            case_id=case_id,
            candidate_id=candidate_id,
            judge_meta=meta,
            redline=redline,
            direction=quality.direction,
            execution=quality.execution,
            verdict_vs_original=vs_original.result,
            pairwise=pairwise_results,
            failure_tags=list(quality.failure_tags),
            confidence=quality.confidence,
        )

    def _pairwise(
        self,
        *,
        left: np.ndarray,
        right: np.ndarray,
        left_label: str,
        right_label: str,
        target_card: TargetCard,
        declared_dimension: str,
    ) -> PairwiseAgreement:
        prompt = render_pairwise_prompt(
            prompts_dir=self.prompts_dir,
            target_card=target_card,
            declared_dimension=declared_dimension,
            left_label=left_label,
            right_label=right_label,
        )
        forward = self.hub.generate_json(
            node="judge_pairwise",
            schema=PairwiseCallOutput,
            user_prompt=prompt,
            images=[left, right],
        ).data
        backward = self.hub.generate_json(
            node="judge_pairwise",
            schema=PairwiseCallOutput,
            user_prompt=prompt,
            images=[right, left],
        ).data
        return reconcile_bidirectional(forward.result, backward.result)

    def _failed_redline_result(
        self,
        *,
        case_id: str,
        candidate_id: str,
        meta: JudgeMeta,
        redline: RedlineResult,
        declared_dimension: str,
    ) -> JudgeResult:
        failure_tags = [item.type for item in redline.violations] or ["redline_fail"]
        return JudgeResult(
            case_id=case_id,
            candidate_id=candidate_id,
            judge_meta=meta,
            redline=redline,
            direction=DirectionResult(
                declared_dimension=declared_dimension,
                hit_target_card=False,
                score=0,
                rationale="Skipped: redline gate failed",
            ),
            execution=ExecutionResult(
                realization=ExecutionDimension(score=0, evidence="skipped"),
                intensity=ExecutionDimension(score=0, evidence="skipped"),
                collateral_damage=ExecutionDimension(score=0, evidence="skipped"),
            ),
            verdict_vs_original=Verdict.WORSE,
            pairwise=[],
            failure_tags=failure_tags,
            confidence=Confidence.LOW,
        )


def _prompt_hash(path: Path) -> str:
    return sha256_prefix(path.read_bytes())
