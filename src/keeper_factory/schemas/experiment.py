from __future__ import annotations

from pydantic import Field

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import (
    ExperimentKind,
    ExperimentStatus,
    Verdict,
)


class StrategyInfo(StrictModel):
    p1_version: str
    candidate_index: int | None = None
    declared_dimension: str
    strategy_digest: str
    injected_knowledge: list[str] = Field(default_factory=list)
    validates_recipe: str | None = None


class EnvInfo(StrictModel):
    vlm: str
    edit_model: str
    judge_model: str
    p1_hash: str
    redline_prompt_hash: str
    quality_prompt_hash: str
    dimension_vocab: str
    anchor_set: str


class Artifacts(StrictModel):
    edit_prompt_url: str | None = None
    result_image_url: str | None = None
    result_image_sha256: str | None = None


class ExecutionScores(StrictModel):
    realization: int
    intensity: int
    collateral_damage: int


class JudgeSummary(StrictModel):
    redline_pass: bool
    verdict_vs_original: Verdict
    direction_score: int
    execution_scores: ExecutionScores
    failure_tags: list[str] = Field(default_factory=list)


class CallCounts(StrictModel):
    vlm: int = 0
    edit: int = 0


class TokenUsageEntry(StrictModel):
    model: str
    input: int = 0
    input_cached: int = 0
    output: int = 0
    output_thinking: int = 0


class ExperimentCost(StrictModel):
    calls: CallCounts = Field(default_factory=CallCounts)
    tokens: list[TokenUsageEntry] = Field(default_factory=list)


class ExperimentRecord(StrictModel):
    exp_id: str
    exp_sig: str
    loop: int
    batch: int
    kind: ExperimentKind
    case_id: str
    strategy: StrategyInfo
    env: EnvInfo
    artifacts: Artifacts = Field(default_factory=Artifacts)
    judge_summary: JudgeSummary | None = None
    judge_result_url: str | None = None
    status: ExperimentStatus
    cost: ExperimentCost = Field(default_factory=ExperimentCost)
    created_at: str


class SignatureIndexEntry(StrictModel):
    sig: str
    exp_id: str
    verdict: str | None = None
    loop: int
