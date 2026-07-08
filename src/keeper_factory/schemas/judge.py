from __future__ import annotations

from pydantic import Field

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import Confidence, Verdict


class JudgeMeta(StrictModel):
    judge_model: str
    redline_prompt_hash: str
    quality_prompt_hash: str
    dimension_vocab: str


class RedlineViolation(StrictModel):
    type: str
    location: str
    evidence: str


class RedlineResult(StrictModel):
    pass_: bool = Field(alias="pass")
    violations: list[RedlineViolation] = Field(default_factory=list)


class DirectionResult(StrictModel):
    declared_dimension: str
    hit_target_card: bool
    score: int
    rationale: str
    missed_better_dimension: str | None = None


class ExecutionDimension(StrictModel):
    score: int
    evidence: str


class ExecutionResult(StrictModel):
    realization: ExecutionDimension
    intensity: ExecutionDimension
    collateral_damage: ExecutionDimension


class PairwiseResult(StrictModel):
    against: str
    result: Verdict
    bidirectional_agreed: bool


class PairwiseCallOutput(StrictModel):
    """Verdict for the FIRST image relative to the SECOND."""

    result: Verdict
    rationale: str | None = None


class QualityCallOutput(StrictModel):
    direction: DirectionResult
    execution: ExecutionResult
    failure_tags: list[str] = Field(default_factory=list)
    confidence: Confidence


class JudgeResult(StrictModel):
    case_id: str
    candidate_id: str
    judge_meta: JudgeMeta
    redline: RedlineResult
    direction: DirectionResult
    execution: ExecutionResult
    verdict_vs_original: Verdict
    pairwise: list[PairwiseResult] = Field(default_factory=list)
    failure_tags: list[str] = Field(default_factory=list)
    confidence: Confidence
