from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from keeper_factory.cli import app
from keeper_factory.healthcheck import CheckStatus, HealthReport, CheckResult


def test_health_report_formatting() -> None:
    report = HealthReport(
        results=[
            CheckResult("env:KF_LLM_API_KEY", CheckStatus.PASS, "set"),
            CheckResult("oss:write", CheckStatus.FAIL, "denied"),
        ]
    )
    lines = report.lines()
    assert report.ok is False
    assert any("Overall: FAILED" in line for line in lines)
    assert any("oss:write" in line for line in lines)


def test_init_skip_secrets_skips_checks(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    payload = json.loads((project_root / "config.example.json").read_text(encoding="utf-8"))
    payload["paths"]["data_root"] = str(tmp_path / "data")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--config", str(config_path), "--skip-secrets"],
    )
    assert result.exit_code == 0, result.stdout
    assert "Environment checks: skipped" in result.stdout
    assert (tmp_path / "data" / "ledger").is_dir()
