from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from keeper_factory.cli import app
from keeper_factory.config import load_config
from keeper_factory.judge.scoring import category_validation_score
from keeper_factory.judge.vocab import is_valid_dimension
from keeper_factory.loop import LoopRuntime
from keeper_factory.loop.ranking import rank_key
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.schemas import CaseCategory, JudgeResult, Verdict
from keeper_factory.schemas.judge import (
    DirectionResult,
    ExecutionDimension,
    ExecutionResult,
    JudgeMeta,
    PairwiseResult,
    RedlineResult,
)


def _judge_result(*, candidate_id: str, verdict: Verdict, pairwise: list[PairwiseResult]) -> JudgeResult:
    meta = JudgeMeta(
        judge_model="test",
        redline_prompt_hash="h1",
        quality_prompt_hash="h2",
        dimension_vocab="dimension_vocab_v0",
    )
    return JudgeResult(
        case_id="case_001",
        candidate_id=candidate_id,
        judge_meta=meta,
        redline=RedlineResult.model_validate({"pass": True, "violations": []}),
        direction=DirectionResult(
            declared_dimension="light_shadow",
            hit_target_card=True,
            score=3,
            rationale="test",
        ),
        execution=ExecutionResult(
            realization=ExecutionDimension(score=3, evidence=""),
            intensity=ExecutionDimension(score=2, evidence=""),
            collateral_damage=ExecutionDimension(score=3, evidence=""),
        ),
        verdict_vs_original=verdict,
        pairwise=pairwise,
        failure_tags=[],
        confidence="medium",
    )


def test_rank_key_prefers_pairwise_wins() -> None:
    winner = _judge_result(
        candidate_id="c1",
        verdict=Verdict.SAME,
        pairwise=[PairwiseResult(against="c2", result=Verdict.BETTER, bidirectional_agreed=True)],
    )
    loser = _judge_result(
        candidate_id="c2",
        verdict=Verdict.BETTER,
        pairwise=[PairwiseResult(against="c1", result=Verdict.WORSE, bidirectional_agreed=True)],
    )
    assert rank_key(category=CaseCategory.BAD, judge_result=winner) < rank_key(
        category=CaseCategory.BAD, judge_result=loser
    )


def test_category_score_good_same_is_positive() -> None:
    result = _judge_result(candidate_id="c1", verdict=Verdict.SAME, pairwise=[])
    assert (
        category_validation_score(
            category=CaseCategory.GOOD,
            redline_pass=True,
            verdict_vs_original=result.verdict_vs_original,
        )
        == 1
    )


def test_f2_edit_prompt_excludes_target_card_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "k")
    monkeypatch.setenv("KF_OSS_AK", "k")
    monkeypatch.setenv("KF_OSS_SK", "k")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "k")

    project_root = Path(__file__).resolve().parents[1]
    loaded = load_config(project_root / "config.example.json", project_root=project_root)
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "secret scene",
            "candidate_dimensions": [{"dimension": "light_shadow", "hint": "secret hint"}],
            "must_keep": ["SECRET_KEEP_MARKER"],
            "forbidden": ["SECRET_FORBIDDEN_MARKER"],
            "problem_note": "secret problem",
        },
    )
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(case_dir / "original.jpg")

    loaded = loaded.__class__(
        config=loaded.config,
        secrets=loaded.secrets,
        config_hash=loaded.config_hash,
        prompts_hash=loaded.prompts_hash,
        project_root=loaded.project_root,
        data_root=data_root,
        prompts_dir=loaded.prompts_dir,
        log_file=data_root / "ledger/logs/kf.log",
    )
    runtime = LoopRuntime(loaded, dry_run=True)
    runtime.run(loops=1)

    prompt_path = data_root / "ledger" / "experiments" / "loop_001" / "loop001_main_c1_edit_prompt.txt"
    text = prompt_path.read_text(encoding="utf-8")
    assert "SECRET_KEEP_MARKER" not in text
    assert "SECRET_FORBIDDEN_MARKER" not in text
    assert "secret hint" not in text


def test_per_experiment_cost_not_cumulative(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "k")
    monkeypatch.setenv("KF_OSS_AK", "k")
    monkeypatch.setenv("KF_OSS_SK", "k")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "k")

    project_root = Path(__file__).resolve().parents[1]
    loaded = load_config(project_root / "config.example.json", project_root=project_root)
    data_root = tmp_path / "data"
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "x",
            "candidate_dimensions": [{"dimension": "composition", "hint": "crop"}],
            "must_keep": ["identity"],
            "forbidden": ["add objects"],
            "problem_note": "x",
        },
    )
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(case_dir / "original.jpg")
    loaded = loaded.__class__(
        config=loaded.config,
        secrets=loaded.secrets,
        config_hash=loaded.config_hash,
        prompts_hash=loaded.prompts_hash,
        project_root=loaded.project_root,
        data_root=data_root,
        prompts_dir=loaded.prompts_dir,
        log_file=data_root / "ledger/logs/kf.log",
    )
    runtime = LoopRuntime(loaded, dry_run=True)
    runtime.run(loops=1)

    costs = []
    for path in sorted((data_root / "ledger" / "experiments" / "loop_001").glob("loop001_main_c[0-9].json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        costs.append(payload["cost"]["calls"]["vlm"])
    assert costs == [0, 0, 0]


def test_declared_dimension_normalized_in_dry_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "k")
    monkeypatch.setenv("KF_OSS_AK", "k")
    monkeypatch.setenv("KF_OSS_SK", "k")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "k")

    project_root = Path(__file__).resolve().parents[1]
    loaded = load_config(project_root / "config.example.json", project_root=project_root)
    data_root = tmp_path / "data"
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "x",
            "candidate_dimensions": [{"dimension": "light_shadow", "hint": "lift"}],
            "must_keep": ["identity"],
            "forbidden": ["add objects"],
            "problem_note": "x",
        },
    )
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(case_dir / "original.jpg")
    loaded = loaded.__class__(
        config=loaded.config,
        secrets=loaded.secrets,
        config_hash=loaded.config_hash,
        prompts_hash=loaded.prompts_hash,
        project_root=loaded.project_root,
        data_root=data_root,
        prompts_dir=loaded.prompts_dir,
        log_file=data_root / "ledger/logs/kf.log",
    )
    runtime = LoopRuntime(loaded, dry_run=True)
    runtime.run(loops=1)
    loop_payload = json.loads((data_root / "ledger" / "loops" / "loop_001.json").read_text(encoding="utf-8"))
    for candidate in loop_payload["candidates"]:
        assert is_valid_dimension(candidate["declared_dimension"])


def test_batch_approval_flow(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "k")
    monkeypatch.setenv("KF_OSS_AK", "k")
    monkeypatch.setenv("KF_OSS_SK", "k")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "k")

    project_root = Path(__file__).resolve().parents[1]
    payload = json.loads((project_root / "config.example.json").read_text(encoding="utf-8"))
    payload["paths"]["data_root"] = str(tmp_path / "data")
    payload["loop"]["batch_size"] = 1
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_config(config_path, project_root=project_root)

    data_root = tmp_path / "data"
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "x",
            "candidate_dimensions": [{"dimension": "light_shadow", "hint": "lift"}],
            "must_keep": ["identity"],
            "forbidden": ["add objects"],
            "problem_note": "x",
        },
    )
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(case_dir / "original.jpg")
    loaded = loaded.__class__(
        config=loaded.config,
        secrets=loaded.secrets,
        config_hash=loaded.config_hash,
        prompts_hash=loaded.prompts_hash,
        project_root=loaded.project_root,
        data_root=data_root,
        prompts_dir=loaded.prompts_dir,
        log_file=data_root / "ledger/logs/kf.log",
    )

    runtime = LoopRuntime(loaded, dry_run=True)
    runtime.run(loops=1)
    assert runtime.store.is_awaiting_approval()

    with pytest.raises(RuntimeError, match="awaiting approval"):
        runtime.run(loops=1)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["approve", "--config", str(config_path), "--text", "all ok"],
    )
    assert result.exit_code == 0, result.stdout
    assert not runtime.store.is_awaiting_approval()

    completed = runtime.run(loops=1)
    assert completed == [2]
