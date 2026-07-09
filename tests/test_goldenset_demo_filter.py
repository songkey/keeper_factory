from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.goldenset import list_case_ids, list_runnable_case_ids
from keeper_factory.loop.validation import pick_validation_cases
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.schemas import CaseCategory


def _write_case(
    data_root: Path,
    case_id: str,
    *,
    demo: bool = False,
    category: str = "bad",
) -> None:
    case_dir = data_root / "goldenset" / case_id
    case_dir.mkdir(parents=True)
    payload = {
        "case_id": case_id,
        "category": category,
        "scene_brief": f"scene {case_id}",
        "candidate_dimensions": [{"dimension": "light_shadow", "hint": "x"}],
        "must_keep": ["identity"],
        "forbidden": ["add objects"],
        "problem_note": "problem",
    }
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
