from __future__ import annotations

from keeper_factory.schemas.experiment import ExecutionScores, JudgeSummary
from keeper_factory.schemas.judge import JudgeResult


def judge_summary_from_result(result: JudgeResult) -> JudgeSummary:
    return JudgeSummary(
        redline_pass=result.redline.pass_,
        verdict_vs_original=result.verdict_vs_original,
        direction_score=result.direction.score,
        execution_scores=ExecutionScores(
            realization=result.execution.realization.score,
            intensity=result.execution.intensity.score,
            collateral_damage=result.execution.collateral_damage.score,
        ),
        failure_tags=list(result.failure_tags),
    )
