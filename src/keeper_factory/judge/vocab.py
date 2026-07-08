"""Closed dimension vocabulary for judge v0."""

from __future__ import annotations

DIMENSION_VOCAB_VERSION = "dimension_vocab_v0"

DIMENSION_VOCAB_V0: dict[str, str] = {
    "light_shadow": "光影氛围 — 光比、方向光、明暗层次",
    "color_mood": "色彩情绪 — 色调、色彩关系、饱和策略",
    "subject_impact": "主体表现力 — 主体突出、清晰度、质感",
    "composition": "构图裁切 — 裁剪、平衡、视觉引导",
    "atmosphere": "氛围叙事 — 天气感、时间感、情绪",
    "moment": "瞬间感 — 动态、表情、抓拍价值",
    "other": "逃生口 — 必须附文字说明",
}


def is_valid_dimension(dimension: str) -> bool:
    return dimension in DIMENSION_VOCAB_V0


def format_vocab_for_prompt() -> str:
    lines = [f"- {key}: {label}" for key, label in DIMENSION_VOCAB_V0.items()]
    return "\n".join(lines)
