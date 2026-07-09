from __future__ import annotations

from keeper_factory.judge.scoring import category_validation_score
from keeper_factory.schemas import CaseCategory, ExperimentRecord, JudgeResult, Verdict


def pairwise_wins(judge_result: JudgeResult) -> int:
    wins = 0
    for item in judge_result.pairwise:
        if item.against == "original":
            continue
        if item.result == Verdict.BETTER:
            wins += 1
    return wins


def execution_total(judge_result: JudgeResult) -> int:
    return (
        judge_result.execution.realization.score
        + judge_result.execution.intensity.score
        + judge_result.execution.collateral_damage.score
    )


def category_score(*, category: CaseCategory, judge_result: JudgeResult) -> int:
    return category_validation_score(
        category=category,
        redline_pass=judge_result.redline.pass_,
        verdict_vs_original=judge_result.verdict_vs_original,
    )


def rank_key(
    *,
    category: CaseCategory,
    judge_result: JudgeResult,
) -> tuple[int, int, int, int]:
    """Lower tuple sorts first (best candidate)."""
    return (
        -pairwise_wins(judge_result),
        -category_score(category=category, judge_result=judge_result),
        -judge_result.direction.score,
        -execution_total(judge_result),
    )


def rank_records(
    records: list[ExperimentRecord],
    *,
    category: CaseCategory,
    judge_results: dict[str, JudgeResult],
) -> list[ExperimentRecord]:
    def sort_key(record: ExperimentRecord) -> tuple[int, int, int, int]:
        result = judge_results.get(record.exp_id)
        if result is None:
            return (0, 0, 0, 0)
        return rank_key(category=category, judge_result=result)

    return sorted(records, key=sort_key)
