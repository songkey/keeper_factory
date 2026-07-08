from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from keeper_factory.cli import app


def _make_temp_config(project_root: Path, tmp_path: Path) -> Path:
    config_example = project_root / "config.example.json"
    payload = json.loads(config_example.read_text(encoding="utf-8"))
    payload["paths"]["data_root"] = str(tmp_path / "data")
    payload["paths"]["data_remote"] = ""
    config_path = tmp_path / "config.e2e.json"
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config_path


def test_cli_e2e_dry_run_flow(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config_path = _make_temp_config(project_root, tmp_path)
    runner = CliRunner()

    seed = runner.invoke(
        app,
        ["seed-demo", "--config", str(config_path), "--skip-secrets"],
    )
    assert seed.exit_code == 0, seed.stdout
    assert "seeded demo assets" in seed.stdout or "already exists" in seed.stdout

    run = runner.invoke(
        app,
        ["run", "--dry-run", "--loops", "1", "--config", str(config_path)],
    )
    assert run.exit_code == 0, run.stdout
    assert "Completed loops: 1" in run.stdout

    status = runner.invoke(app, ["status", "--config", str(config_path)])
    assert status.exit_code == 0, status.stdout
    assert "running: False" in status.stdout
    assert "checkpoint_exists: False" in status.stdout

    data_root = tmp_path / "data"
    assert (data_root / "goldenset" / "case_001" / "target_card.yaml").is_file()
    assert (data_root / "ledger" / "loops" / "loop_001.json").is_file()
    assert (data_root / "ledger" / "reports" / "loop_001.md").is_file()
    assert not (data_root / "ledger" / "checkpoint.json").exists()
