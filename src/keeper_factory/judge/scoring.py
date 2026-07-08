from __future__ import annotations

from keeper_factory.schemas.enums import CaseCategory, Verdict
from keeper_factory.schemas.judge import JudgeResult


def category_validation_score(
    *,
    category: CaseCategory,
    redline_pass: bool,
    verdict_vs_original: Verdict | None,
) -> int:
    if category == CaseCategory.REDLINE:
        if redline_pass:
            return 1
        return -3

    if not redline_pass:
        return -2

    if verdict_vs_original is None:
        return 0

    if category == CaseCategory.BAD:
        if verdict_vs_original == Verdict.BETTER:
            return 1
        if verdict_vs_original == Verdict.SAME:
            return 0
        return -1

    if category == CaseCategory.GOOD:
        if verdict_vs_original in {Verdict.SAME, Verdict.BETTER}:
            return 1
        return -2

    return 0


def score_judge_result(category: CaseCategory, result: JudgeResult) -> int:
    return category_validation_score(
        category=category,
        redline_pass=result.redline.pass_,
        verdict_vs_original=result.verdict_vs_original,
    )
