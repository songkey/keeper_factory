from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.memory.yaml_io import load_yaml_dict
from keeper_factory.schemas.target_card import TargetCard


def case_dir(data_root: Path, case_id: str) -> Path:
    return data_root / "goldenset" / case_id


def list_case_ids(data_root: Path, *, include_demo: bool = True) -> list[str]:
    """List goldenset case ids.

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
    return TargetCard.model_validate(load_yaml_dict(path))


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
