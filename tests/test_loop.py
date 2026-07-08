from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from typer.testing import CliRunner

from keeper_factory.cli import app
from keeper_factory.config import load_config
from keeper_factory.loop import LoopRuntime
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.schemas import LoopStage


def _set_env(monkeypatch) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("KF_OSS_AK", "test-oss-ak")
    monkeypatch.setenv("KF_OSS_SK", "test-oss-sk")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "test-mail-pass")


def _init_data_repo(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=data_root, check=False, capture_output=True, text=True)
    (data_root / "ledger").mkdir(parents=True, exist_ok=True)
    (data_root / "memory").mkdir(parents=True, exist_ok=True)
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True, exist_ok=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "sunset portrait",
            "candidate_dimensions": [{"dimension": "light_shadow", "hint": "lift subject"}],
            "must_keep": ["identity"],
            "forbidden": ["add objects"],
            "problem_note": "subject underexposed",
        },
    )
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8), mode="RGB").save(
        case_dir / "original.png"
    )


def _clone_loaded(loaded, data_root: Path):
    return loaded.__class__(
        config=loaded.config,
        secrets=loaded.secrets,
        config_hash=loaded.config_hash,
        prompts_hash=loaded.prompts_hash,
        project_root=loaded.project_root,
        data_root=data_root,
        prompts_dir=loaded.prompts_dir,
        log_file=data_root / loaded.config.logging.file,
    )


def test_loop_runtime_run_and_status(monkeypatch, tmp_path: Path) -> None:
    _set_env(monkeypatch)
    project_root = Path(__file__).resolve().parents[1]
    loaded = load_config(project_root / "config.example.json", project_root=project_root)
    data_root = tmp_path / "data"
    _init_data_repo(data_root)
    loaded = _clone_loaded(loaded, data_root)

    runtime = LoopRuntime(loaded, dry_run=True)
    completed = runtime.run(loops=2)
    assert completed == [1, 2]

    assert runtime.store.load() is None
    status = runtime.status()
    assert status.running is False
    assert status.loop == 2
    assert status.checkpoint_exists is False

    loop_file = data_root / "ledger" / "loops" / "loop_002.json"
    assert loop_file.is_file()
    payload = json.loads(loop_file.read_text(encoding="utf-8"))
    assert payload["stage_history"][-1] == "batch_wait"


def test_loop_runtime_resume(monkeypatch, tmp_path: Path) -> None:
    _set_env(monkeypatch)
    project_root = Path(__file__).resolve().parents[1]
    loaded = load_config(project_root / "config.example.json", project_root=project_root)
    data_root = tmp_path / "data"
    _init_data_repo(data_root)
    loaded = _clone_loaded(loaded, data_root)
    runtime = LoopRuntime(loaded, dry_run=True)
    runtime.store.save(loop=3, batch=1, stage=LoopStage.F4A)
    resumed = runtime.resume(force=False)
    assert resumed == 3
    assert runtime.store.load() is None


def test_cli_status(monkeypatch) -> None:
    _set_env(monkeypatch)
    project_root = Path(__file__).resolve().parents[1]
    cfg = project_root / "config.example.json"
    runner = CliRunner()
    result = runner.invoke(app, ["status", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "running:" in result.stdout
