from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from keeper_factory.goldenset import (
    list_case_ids,
    list_runnable_case_ids,
    load_target_card,
    next_case_id,
)
from keeper_factory.loop.stages import pick_case_for_loop
from keeper_factory.loop.validation import pick_validation_cases
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.schemas import CaseCategory


def _write_case(
    data_root: Path,
    case_id: str,
    *,
    demo: bool = False,
    category: str = "bad",
    card_case_id: str | None = None,
) -> None:
    case_dir = data_root / "goldenset" / case_id
    case_dir.mkdir(parents=True)
    payload = {
        "case_id": card_case_id or case_id,
        "category": category,
        "scene_brief": f"scene {case_id}",
        "candidate_dimensions": [{"dimension": "light_shadow", "hint": "x"}],
        "must_keep": ["identity"],
        "forbidden": ["add objects"],
        "problem_note": "problem",
    }
    if category == "good":
        payload.pop("problem_note")
        payload["established_note"] = "ok"
    if category == "redline":
        payload.pop("problem_note", None)
        payload["trap_note"] = "trap"
    if demo:
        payload["demo"] = True
    dump_yaml_dict(case_dir / "target_card.yaml", payload)
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(
        case_dir / "original.png"
    )


def test_list_runnable_excludes_demo_when_real_cases_exist(tmp_path: Path) -> None:
    _write_case(tmp_path, "case_001", demo=True)
    _write_case(tmp_path, "case_002")
    _write_case(tmp_path, "case_003")

    assert list_case_ids(tmp_path) == ["case_001", "case_002", "case_003"]
    assert list_runnable_case_ids(tmp_path) == ["case_002", "case_003"]


def test_list_runnable_falls_back_to_demo_only(tmp_path: Path) -> None:
    _write_case(tmp_path, "case_001", demo=True)
    assert list_runnable_case_ids(tmp_path) == ["case_001"]


def test_pick_validation_skips_demo_case(tmp_path: Path) -> None:
    _write_case(tmp_path, "case_001", demo=True)
    _write_case(tmp_path, "case_002")
    _write_case(tmp_path, "case_005")
    _write_case(tmp_path, "case_006")

    picked = pick_validation_cases(
        tmp_path,
        category=CaseCategory.BAD,
        discovery_case_id="case_005",
        k=3,
    )
    assert "case_001" not in picked
    assert picked[0] == "case_002"
    assert "case_005" not in picked


def test_sparse_case_ids_supported_for_sampling_and_append(tmp_path: Path) -> None:
    """Missing case_001 (or any gap) must not break F.1 / F.4a / import allocation."""
    _write_case(tmp_path, "case_002", category="bad")
    _write_case(tmp_path, "case_005", category="bad")
    _write_case(tmp_path, "case_010", category="good")
    _write_case(tmp_path, "case_014", category="redline")

    assert list_runnable_case_ids(tmp_path) == [
        "case_002",
        "case_005",
        "case_010",
        "case_014",
    ]
    assert next_case_id(tmp_path / "goldenset") == "case_015"

    case_id, category = pick_case_for_loop(tmp_path, loop_no=1)
    assert case_id == "case_002"
    assert category == CaseCategory.BAD

    picked = pick_validation_cases(
        tmp_path,
        category=CaseCategory.BAD,
        discovery_case_id="case_005",
        k=3,
    )
    assert picked == ["case_002"]

    # Append another case with a gap-friendly id; sampling still works.
    _write_case(tmp_path, "case_015", category="bad")
    assert list_runnable_case_ids(tmp_path)[-1] == "case_015"
    assert next_case_id(tmp_path / "goldenset") == "case_016"


def test_target_card_case_id_must_match_directory(tmp_path: Path) -> None:
    _write_case(tmp_path, "case_002", card_case_id="case_999")
    with pytest.raises(ValueError, match="does not match directory"):
        load_target_card(tmp_path, "case_002")
