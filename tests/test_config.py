from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from keeper_factory.config import (
    AppConfig,
    compute_config_hash,
    compute_prompts_hash,
    load_config,
)
from keeper_factory.schemas import (
    CaseCategory,
    ExperimentKind,
    ExperimentRecord,
    ExperimentStatus,
    TargetCard,
    Verdict,
)
from keeper_factory.schemas.experiment import (
    Artifacts,
    EnvInfo,
    ExecutionScores,
    ExperimentCost,
    JudgeSummary,
    StrategyInfo,
)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def example_config_path(project_root: Path) -> Path:
    return project_root / "config.example.json"


@pytest.fixture
def env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KF_LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("KF_OSS_AK", "test-oss-ak")
    monkeypatch.setenv("KF_OSS_SK", "test-oss-sk")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "test-mail-pass")


def test_load_example_config(example_config_path: Path, env_vars: None, project_root: Path) -> None:
    loaded = load_config(example_config_path, project_root=project_root)
    assert loaded.config.loop.batch_size == 5
    assert loaded.secrets.api_key == "test-llm-key"
    assert len(loaded.config_hash) == 64
    assert len(loaded.prompts_hash) == 64


def test_missing_env_fails_fast(example_config_path: Path, project_root: Path) -> None:
    for key in ("KF_LLM_API_KEY", "KF_OSS_AK", "KF_OSS_SK", "KF_MAIL_PASSWORD"):
        os.environ.pop(key, None)
    with pytest.raises(RuntimeError, match="KF_LLM_API_KEY"):
        load_config(example_config_path, project_root=project_root)


def test_config_hash_stable(example_config_path: Path, project_root: Path) -> None:
    raw = json.loads(example_config_path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)
    h1 = compute_config_hash(config)
    h2 = compute_config_hash(config)
    assert h1 == h2


def test_prompts_hash_includes_t0(project_root: Path) -> None:
    h = compute_prompts_hash(project_root / "prompts")
    assert len(h) == 64


def test_target_card_bad_requires_problem_note() -> None:
    with pytest.raises(ValueError, match="problem_note"):
        TargetCard(
            case_id="case_001",
            category=CaseCategory.BAD,
            scene_brief="test",
            candidate_dimensions=[{"dimension": "light_shadow", "hint": "fix light"}],
        )


def test_experiment_record_roundtrip() -> None:
    record = ExperimentRecord(
        exp_id="loop001_main_c1",
        exp_sig="sha256:abc",
        loop=1,
        batch=1,
        kind=ExperimentKind.MAIN,
        case_id="case_001",
        strategy=StrategyInfo(
            p1_version="p1_v001",
            candidate_index=1,
            declared_dimension="light_shadow",
            strategy_digest="sha256:def",
        ),
        env=EnvInfo(
            vlm="gpt-5.5",
            edit_model="gpt-image-2",
            judge_model="gpt-5.5",
            p1_hash="h1",
            redline_prompt_hash="h2",
            quality_prompt_hash="h3",
            dimension_vocab="dimension_vocab_v0",
            anchor_set="anchor_v0",
        ),
        artifacts=Artifacts(),
        judge_summary=JudgeSummary(
            redline_pass=True,
            verdict_vs_original=Verdict.BETTER,
            direction_score=3,
            execution_scores=ExecutionScores(
                realization=3, intensity=2, collateral_damage=4
            ),
        ),
        status=ExperimentStatus.COMPLETED,
        cost=ExperimentCost(),
        created_at="2026-07-08T12:00:00+08:00",
    )
    data = record.model_dump(mode="json")
    restored = ExperimentRecord.model_validate(data)
    assert restored.exp_id == "loop001_main_c1"
