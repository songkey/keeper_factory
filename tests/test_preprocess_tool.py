from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image


def _load_module():
    project_root = Path(__file__).resolve().parents[1]
    tool_path = project_root / "tools" / "preprocess_goldenset.py"
    spec = importlib.util.spec_from_file_location("preprocess_goldenset", tool_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_sources(tmp_path: Path) -> None:
    mod = _load_module()
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    specs = mod.parse_sources([f"bad:{bad_dir}"])
    assert len(specs) == 1
    assert specs[0].category == "bad"


def test_preprocess_image_resize(tmp_path: Path) -> None:
    mod = _load_module()
    src = tmp_path / "in.png"
    out = tmp_path / "out.jpg"
    Image.new("RGB", (3200, 1200), color=(128, 100, 90)).save(src)
    digest, size = mod.preprocess_image(src, out, max_edge=2048)
    assert out.is_file()
    assert size[0] <= 2048 and size[1] <= 2048
    assert isinstance(digest, str) and len(digest) == 64


def test_build_target_card_category_fields() -> None:
    mod = _load_module()
    card_bad = mod.build_target_card(case_id="case_001", category="bad", prelabel=None)
    card_good = mod.build_target_card(case_id="case_002", category="good", prelabel=None)
    card_red = mod.build_target_card(case_id="case_003", category="redline", prelabel=None)
    assert "problem_note" in card_bad
    assert "established_note" in card_good
    assert "trap_note" in card_red


def test_next_case_id_allows_gaps(tmp_path: Path) -> None:
    mod = _load_module()
    goldenset = tmp_path / "goldenset"
    (goldenset / "case_002").mkdir(parents=True)
    (goldenset / "case_014").mkdir(parents=True)
    (goldenset / "anchors").mkdir(parents=True)
    assert mod.next_case_id(goldenset) == "case_015"
