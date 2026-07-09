from __future__ import annotations

from pathlib import Path

from keeper_factory.loop.edit_prompt import (
    build_seed_edit_prompt,
    render_j1_prompt,
    sanitize_edit_prompt,
)


def test_sanitize_rejects_done_and_meta_prefix() -> None:
    fallback = build_seed_edit_prompt(
        declared_dimension="color_mood",
        strategy_summary="warm the tone gently",
    )
    assert sanitize_edit_prompt("Done.", fallback=fallback) == fallback
    assert sanitize_edit_prompt("done", fallback=fallback) == fallback
    assert sanitize_edit_prompt("已完成。", fallback=fallback) == fallback

    meta = (
        "已按“color_mood”方向优化：统一偏暗室内照片的暖调氛围，"
        "弱化肤色偏黄与背景脏黄/绿反光。"
    )
    cleaned = sanitize_edit_prompt(meta, fallback=fallback)
    assert cleaned.startswith("统一偏暗室内照片的暖调氛围")
    assert "已按" not in cleaned


def test_sanitize_keeps_imperative_prompt() -> None:
    fallback = "fallback"
    text = (
        "Slightly warm the indoor lighting, clean dirty yellow/green bounce on walls, "
        "and keep skin tones natural without heavy retouching."
    )
    assert sanitize_edit_prompt(text, fallback=fallback) == text


def test_j1_template_mentions_edit_model_only(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    prompts_dir = project_root / "prompts"
    j1 = render_j1_prompt(
        prompts_dir=prompts_dir,
        declared_dimension="color_mood",
        strategy_summary="让暖调更干净",
    )
    assert "image-edit" in j1.lower() or "Image Edit" in j1 or "image edit" in j1.lower()
    assert "color_mood" in j1
    assert "让暖调更干净" in j1
    assert "Done" in j1  # as a forbidden example in rules
