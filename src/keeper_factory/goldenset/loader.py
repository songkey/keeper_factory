from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.memory.yaml_io import load_yaml_dict
from keeper_factory.schemas.target_card import TargetCard

_CASE_ID_RE = re.compile(r"^case_(\d+)$")


def case_dir(data_root: Path, case_id: str) -> Path:
    return data_root / "goldenset" / case_id


def parse_case_index(case_id: str) -> int | None:
    """Return the numeric suffix of ``case_NNN``, or None if not that pattern."""
    match = _CASE_ID_RE.match(case_id)
    if not match:
        return None
    return int(match.group(1))


def next_case_id(goldenset_root: Path) -> str:
    """Allocate the next ``case_NNN`` id from existing directories.

    Gaps are allowed: if only ``case_002`` and ``case_014`` exist, returns
    ``case_015``. Non-``case_*`` directories are ignored.
    """
    max_idx = 0
    if goldenset_root.is_dir():
        for path in goldenset_root.iterdir():
            if not path.is_dir():
                continue
            idx = parse_case_index(path.name)
            if idx is not None:
                max_idx = max(max_idx, idx)
    return f"case_{max_idx + 1:03d}"


def list_case_ids(data_root: Path, *, include_demo: bool = True) -> list[str]:
    """List goldenset case ids by scanning directories (order is lexical).

    Case numbers need not be contiguous — missing ``case_001`` is fine.
    When ``include_demo`` is False, cases marked ``demo: true`` are omitted.
    """
    root = data_root / "goldenset"
    if not root.is_dir():
        return []
    case_ids = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "target_card.yaml").is_file()
    )
    if include_demo:
        return case_ids
    return [case_id for case_id in case_ids if not is_demo_case(data_root, case_id)]


def list_runnable_case_ids(data_root: Path) -> list[str]:
    """Cases eligible for F.1 / F.4a sampling.

    Prefer non-demo cases. If the goldenset only has demo placeholders
    (``kf seed-demo`` dry-run), fall back to those so local E2E still works.
    Sampling uses this list as-is; sparse ids and later appends are supported.
    """
    real = list_case_ids(data_root, include_demo=False)
    if real:
        return real
    return list_case_ids(data_root, include_demo=True)


def is_demo_case(data_root: Path, case_id: str) -> bool:
    try:
        return bool(load_target_card(data_root, case_id).demo)
    except Exception:
        return False


def load_target_card(data_root: Path, case_id: str) -> TargetCard:
    path = case_dir(data_root, case_id) / "target_card.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"target card not found: {path}")
    card = TargetCard.model_validate(load_yaml_dict(path))
    if card.case_id != case_id:
        raise ValueError(
            f"target_card.case_id={card.case_id!r} does not match directory {case_id!r}"
        )
    return card


def _image_to_rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def load_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    return _image_to_rgb_array(Image.open(path))


def load_original_image(data_root: Path, case_id: str) -> np.ndarray:
    directory = case_dir(data_root, case_id)
    for name in ("original.jpg", "original.jpeg", "original.png"):
        candidate = directory / name
        if candidate.is_file():
            return load_image(candidate)
    raise FileNotFoundError(f"original image not found under {directory}")
