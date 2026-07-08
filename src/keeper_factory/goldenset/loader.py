from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.memory.yaml_io import load_yaml_dict
from keeper_factory.schemas.target_card import TargetCard


def case_dir(data_root: Path, case_id: str) -> Path:
    return data_root / "goldenset" / case_id


def list_case_ids(data_root: Path) -> list[str]:
    root = data_root / "goldenset"
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "target_card.yaml").is_file()
    )


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
