from __future__ import annotations

import json
from pathlib import Path

from keeper_factory.loop.synthesis import SynthesisResult
from keeper_factory.loop.validation import ValidationCampaignResult
from keeper_factory.schemas import ExperimentRecord


def _stagnation_flag(loops_root: Path, *, current_loop: int, threshold: int) -> bool:
    if threshold <= 0 or current_loop < threshold:
        return False
    recent_scores: list[int] = []
    for loop_no in range(current_loop - threshold + 1, current_loop + 1):
        path = loops_root / f"loop_{loop_no:03d}.json"
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        score = payload.get("main_score")
        if score is None:
            return False
        recent_scores.append(int(score))
    if len(recent_scores) < threshold:
        return False
    return max(recent_scores) == min(recent_scores)


def build_loop_report(
    *,
    state,
    records: list[ExperimentRecord],
    validation: ValidationCampaignResult | None,
    synthesis: SynthesisResult | None,
    loops_root: Path,
    stagnation_threshold: int,
    dnr_skipped: int = 0,
) -> tuple[str, list[str], int | None]:
    matrix_lines = [
        "| exp_id | kind | verdict | redline | dir | cat_score |",
        "|---|---|---|---|---|---|",
    ]
    verdict_counts: dict[str, int] = {}
    main_score: int | None = None

    for record in records:
        summary = record.judge_summary
        if summary is None:
            continue
        verdict = summary.verdict_vs_original.value
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        matrix_lines.append(
            f"| {record.exp_id} | {record.kind.value} | {verdict} | "
            f"{summary.redline_pass} | {summary.direction_score} | - |"
        )
        if record.exp_id == state.top_candidate_id and state.category:
            from keeper_factory.judge.scoring import category_validation_score
            from keeper_factory.schemas import CaseCategory, Verdict as V

            main_score = category_validation_score(
                category=CaseCategory(state.category),
                redline_pass=summary.redline_pass,
                verdict_vs_original=V(verdict),
            )

    if validation and validation.outcomes:
        matrix_lines.append("")
        matrix_lines.append("### Validation samples")
        matrix_lines.append("| exp_id | case | score | verdict |")
        matrix_lines.append("|---|---|---|---|")
        for item in validation.outcomes:
            matrix_lines.append(
                f"| {item.exp_id} | {item.case_id} | {item.score} | "
                f"{item.verdict.value if item.verdict else '-'} |"
            )

    knowledge_lines: list[str] = []
    if synthesis:
        if synthesis.promoted_ids:
            knowledge_lines.append(f"- Promoted pattern patches: {', '.join(synthesis.promoted_ids)}")
        if synthesis.failure_note_ids:
            knowledge_lines.append(f"- New failure notes: {', '.join(synthesis.failure_note_ids)}")
        if synthesis.discarded_recipe_ids:
            knowledge_lines.append(f"- Discarded recipes: {', '.join(synthesis.discarded_recipe_ids)}")
    if not knowledge_lines:
        knowledge_lines.append("- (no knowledge changes)")

    stagnation = _stagnation_flag(
        loops_root,
        current_loop=state.loop,
        threshold=stagnation_threshold,
    )

    hypothesis = (
        f"Loop {state.loop} explores {state.case_id} ({state.category}) "
        f"with {len(state.candidates)} candidates."
    )
    next_plan = "Continue category rotation."
    if stagnation:
        next_plan = "STAGNATION: consider strategy-level P.1 rewrite and human review."
    if state.category == "good":
        next_plan = "Good-case protection: prioritize regression checks."

    short_summary = list(state.summary_lines)
    if dnr_skipped:
        short_summary.append(f"dnr_skipped={dnr_skipped}")
    if main_score is not None:
        short_summary.append(f"main_score={main_score}")
    if validation:
        short_summary.append(f"validation_score={validation.total_score}")
    if synthesis and synthesis.promoted_ids:
        short_summary.append(f"promoted={','.join(synthesis.promoted_ids)}")

    lines = [
        f"# Loop {state.loop} Report",
        "",
        f"- Batch: {state.batch}",
        f"- Case: {state.case_id}",
        f"- Category: {state.category}",
        f"- Top candidate: {state.top_candidate_id}",
        f"- Top recipe: {state.top_recipe_id}",
        "",
        "## Hypothesis",
        hypothesis,
        "",
        "## Experiment matrix",
        *matrix_lines,
        "",
        "## Result distribution",
        *[f"- {key}: {count}" for key, count in sorted(verdict_counts.items())],
        "",
        "## Knowledge changes",
        *knowledge_lines,
        "",
        "## Next round plan",
        next_plan,
        "",
        "## Stagnation check",
        f"- flagged: {stagnation}",
        "",
        "## Short summary",
        *[f"- {item}" for item in short_summary],
    ]
    return "\n".join(lines) + "\n", short_summary, main_score
