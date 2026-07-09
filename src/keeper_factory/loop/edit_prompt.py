from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape

from keeper_factory.models.hub import ModelHub

_META_PREFIX_RE = re.compile(
    r"^(?:"
    r"done\.?|ok\.?|okay\.?|已完成[。.!！]?"
    r"|已按[「\"'“].*?[」\"'”]?方向优化[^：:\n]*[：:]\s*"
    r"|已按.*?方向优化[^：:\n]*[：:]\s*"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_BAD_ONLY_RE = re.compile(
    r"^(done\.?|ok\.?|okay\.?|已完成[。.!！]?)$",
    re.IGNORECASE,
)


def build_seed_edit_prompt(*, declared_dimension: str, strategy_summary: str) -> str:
    strategy = (strategy_summary or "").strip() or "improve the photo naturally"
    return (
        f"Edit this photo along dimension '{declared_dimension}'.\n"
        f"Apply the following strategy while preserving identity and scene structure:\n"
        f"{strategy}"
    )


def render_j1_prompt(
    *,
    prompts_dir: Path,
    declared_dimension: str,
    strategy_summary: str,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(prompts_dir)),
        autoescape=select_autoescape(enabled_extensions=()),
    )
    template = env.get_template("j1_edit_prompt.jinja")
    return template.render(
        declared_dimension=declared_dimension,
        strategy_summary=(strategy_summary or "").strip(),
    ).strip()


def sanitize_edit_prompt(raw: str, *, fallback: str) -> str:
    """Reject meta/ack outputs; keep usable imperative edit instructions."""
    text = (raw or "").strip()
    if not text:
        return fallback.strip()

    # Drop accidental markdown fences.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if _BAD_ONLY_RE.match(text):
        return fallback.strip()

    # Strip a leading meta status clause once, keep the actionable remainder.
    stripped = _META_PREFIX_RE.sub("", text, count=1).strip()
    if stripped and stripped != text:
        text = stripped

    if len(text) < 20:
        return fallback.strip()

    # Still looks like a past-tense status report with no actionable body.
    lowered = text.lower()
    if lowered.startswith(("done", "i have ", "i've ", "已按", "已完成")):
        return fallback.strip()

    return text


def generate_image_edit_prompt(
    *,
    hub: ModelHub,
    prompts_dir: Path,
    original: np.ndarray,
    declared_dimension: str,
    strategy_summary: str,
    dry_run: bool | None = None,
) -> tuple[str, str]:
    """Return ``(j1_prompt, edit_prompt)``.

    ``j1_prompt`` is what we send to the VLM.
    ``edit_prompt`` is what we send to the image-edit model.
    """
    j1_prompt = render_j1_prompt(
        prompts_dir=prompts_dir,
        declared_dimension=declared_dimension,
        strategy_summary=strategy_summary,
    )
    seed = build_seed_edit_prompt(
        declared_dimension=declared_dimension,
        strategy_summary=strategy_summary,
    )
    use_dry_run = hub.dry_run if dry_run is None else dry_run
    if use_dry_run:
        return j1_prompt, seed

    hub.reset_cost()
    raw = hub.generate_text(
        node="f2_edit_prompt",
        system_prompt="",
        user_prompt=j1_prompt,
        images=[original],
    )
    edit_prompt = sanitize_edit_prompt(raw, fallback=seed)
    return j1_prompt, edit_prompt
