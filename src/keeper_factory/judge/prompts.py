from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from keeper_factory.judge.anchors import AnchorSet
from keeper_factory.judge.vocab import format_vocab_for_prompt
from keeper_factory.schemas.target_card import TargetCard


def _env(prompts_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(prompts_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_redline_prompt(
    *,
    prompts_dir: Path,
    target_card: TargetCard,
    declared_dimension: str,
    anchor_set: AnchorSet,
) -> str:
    template = _env(prompts_dir).get_template("p3_eval_redline.jinja")
    return template.render(
        target_card=target_card.model_dump(mode="json"),
        declared_dimension=declared_dimension,
        must_keep=target_card.must_keep,
        forbidden=target_card.forbidden,
        anchor_examples=anchor_set.render_few_shot(),
    )


def render_quality_prompt(
    *,
    prompts_dir: Path,
    target_card: TargetCard,
    declared_dimension: str,
    anchor_set: AnchorSet,
) -> str:
    template = _env(prompts_dir).get_template("p3_eval_quality.jinja")
    return template.render(
        target_card_json=json.dumps(target_card.model_dump(mode="json"), ensure_ascii=False, indent=2),
        target_card=target_card.model_dump(mode="json"),
        declared_dimension=declared_dimension,
        dimension_vocab=format_vocab_for_prompt(),
        anchor_examples=anchor_set.render_few_shot(),
    )


def render_pairwise_prompt(
    *,
    prompts_dir: Path,
    target_card: TargetCard,
    declared_dimension: str,
    left_label: str,
    right_label: str,
) -> str:
    template = _env(prompts_dir).get_template("p3_eval_pairwise.jinja")
    return template.render(
        target_card=target_card.model_dump(mode="json"),
        declared_dimension=declared_dimension,
        left_label=left_label,
        right_label=right_label,
        category=target_card.category.value,
    )
