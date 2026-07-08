from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import numpy as np
import pytest
from pydantic import BaseModel

from keeper_factory.config import load_config
from keeper_factory.goldenset.loader import list_case_ids, load_target_card
from keeper_factory.judge import (
    JudgeOrchestrator,
    OpponentCandidate,
    category_validation_score,
    judge_summary_from_result,
    reconcile_bidirectional,
    render_redline_prompt,
    score_judge_result,
)
from keeper_factory.judge.anchors import AnchorSet
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.models.generate_json import GenerateJsonResult
from keeper_factory.models.hub import ModelHub, ResolvedNode
from keeper_factory.schemas.enums import CaseCategory, Confidence, Verdict
from keeper_factory.schemas.judge import (
    DirectionResult,
    ExecutionDimension,
    ExecutionResult,
    JudgeMeta,
    JudgeResult,
    PairwiseCallOutput,
    QualityCallOutput,
    RedlineResult,
    RedlineViolation,
)

T = TypeVar("T", bound=BaseModel)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def loaded_config(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KF_LLM_API_KEY", "test-key")
    monkeypatch.setenv("KF_OSS_AK", "ak")
    monkeypatch.setenv("KF_OSS_SK", "sk")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "mail")
    return load_config(project_root / "config.example.json", project_root=project_root)


def test_reconcile_bidirectional_agreed() -> None:
    agreed = reconcile_bidirectional(Verdict.BETTER, Verdict.WORSE)
    assert agreed.result == Verdict.BETTER
    assert agreed.bidirectional_agreed is True

    disagreed = reconcile_bidirectional(Verdict.BETTER, Verdict.BETTER)
    assert disagreed.result == Verdict.SAME
    assert disagreed.bidirectional_agreed is False


def test_category_validation_score() -> None:
    assert category_validation_score(
        category=CaseCategory.BAD,
        redline_pass=True,
        verdict_vs_original=Verdict.BETTER,
    ) == 1
    assert category_validation_score(
        category=CaseCategory.GOOD,
        redline_pass=True,
        verdict_vs_original=Verdict.SAME,
    ) == 1
    assert category_validation_score(
        category=CaseCategory.REDLINE,
        redline_pass=False,
        verdict_vs_original=None,
    ) == -3


def _target_card_dict(case_id: str = "case_001") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": "bad",
        "scene_brief": "sunset portrait",
        "candidate_dimensions": [
            {"dimension": "light_shadow", "hint": "lift subject, tame sky"}
        ],
        "must_keep": ["identity"],
        "forbidden": ["add objects"],
        "problem_note": "subject underexposed",
    }


def test_render_redline_prompt(loaded_config) -> None:
    from keeper_factory.schemas.target_card import TargetCard

    card = TargetCard.model_validate(_target_card_dict())
    text = render_redline_prompt(
        prompts_dir=loaded_config.prompts_dir,
        target_card=card,
        declared_dimension="light_shadow",
        anchor_set=AnchorSet(version="anchor_v0"),
    )
    assert "light_shadow" in text
    assert "case_001" in text


def test_goldenset_loader_roundtrip(tmp_path: Path) -> None:
    case = tmp_path / "goldenset" / "case_001"
    case.mkdir(parents=True)
    dump_yaml_dict(case / "target_card.yaml", _target_card_dict())
    assert list_case_ids(tmp_path) == ["case_001"]
    card = load_target_card(tmp_path, "case_001")
    assert card.case_id == "case_001"
    assert card.category == CaseCategory.BAD


class _FakeHub:
    def __init__(self, loaded_config, responses: list[dict[str, Any]]) -> None:
        self.loaded = loaded_config
        self._responses = responses

    def resolve_node(self, node: str) -> ResolvedNode:
        return ModelHub.from_loaded(self.loaded).resolve_node(node)  # type: ignore[arg-type]

    def generate_json(self, *, node: str, schema: type[T], **kwargs: Any) -> GenerateJsonResult:
        payload = self._responses.pop(0)
        data = schema.model_validate(payload)
        return GenerateJsonResult(data=data, raw_output="{}", repair_attempted=False)


def _sample_result(case_id: str = "case_001") -> JudgeResult:
    meta = JudgeMeta(
        judge_model="gpt-5.5",
        redline_prompt_hash="h1",
        quality_prompt_hash="h2",
        dimension_vocab="dimension_vocab_v0",
    )
    return JudgeResult(
        case_id=case_id,
        candidate_id="c1",
        judge_meta=meta,
        redline=RedlineResult(pass_=True, violations=[]),
        direction=DirectionResult(
            declared_dimension="light_shadow",
            hit_target_card=True,
            score=3,
            rationale="ok",
        ),
        execution=ExecutionResult(
            realization=ExecutionDimension(score=3, evidence="ok"),
            intensity=ExecutionDimension(score=2, evidence="ok"),
            collateral_damage=ExecutionDimension(score=4, evidence="ok"),
        ),
        verdict_vs_original=Verdict.BETTER,
        failure_tags=[],
        confidence=Confidence.HIGH,
    )


def test_judge_summary_from_result() -> None:
    summary = judge_summary_from_result(_sample_result())
    assert summary.redline_pass is True
    assert summary.direction_score == 3


def test_orchestrator_redline_fail_short_circuit(loaded_config) -> None:
    original = np.zeros((8, 8, 3), dtype=np.uint8)
    candidate = np.ones((8, 8, 3), dtype=np.uint8) * 255
    from keeper_factory.schemas.target_card import TargetCard

    card = TargetCard.model_validate(_target_card_dict())
    hub = _FakeHub(
        loaded_config,
        [
            {
                "pass": False,
                "violations": [
                    {
                        "type": "identity",
                        "location": "face",
                        "evidence": "face changed",
                    }
                ],
            }
        ],
    )
    orchestrator = JudgeOrchestrator.from_hub(hub)  # type: ignore[arg-type]
    result = orchestrator.judge(
        case_id="case_001",
        candidate_id="c1",
        original=original,
        candidate=candidate,
        target_card=card,
        declared_dimension="light_shadow",
    )
    assert result.redline.pass_ is False
    assert result.verdict_vs_original == Verdict.WORSE
    assert result.direction.rationale.startswith("Skipped")
    assert score_judge_result(card.category, result) == -2


def test_orchestrator_full_flow_with_pairwise(loaded_config) -> None:
    original = np.zeros((8, 8, 3), dtype=np.uint8)
    candidate = np.ones((8, 8, 3), dtype=np.uint8) * 200
    opponent = np.ones((8, 8, 3), dtype=np.uint8) * 128
    from keeper_factory.schemas.target_card import TargetCard

    card = TargetCard.model_validate(_target_card_dict())
    hub = _FakeHub(
        loaded_config,
        [
            {"pass": True, "violations": []},
            {
                "direction": {
                    "declared_dimension": "light_shadow",
                    "hit_target_card": True,
                    "score": 3,
                    "rationale": "good",
                },
                "execution": {
                    "realization": {"score": 3, "evidence": "e"},
                    "intensity": {"score": 2, "evidence": "e"},
                    "collateral_damage": {"score": 4, "evidence": "e"},
                },
                "failure_tags": [],
                "confidence": "high",
            },
            {"result": "better", "rationale": "forward"},
            {"result": "worse", "rationale": "backward"},
            {"result": "same", "rationale": "forward2"},
            {"result": "same", "rationale": "backward2"},
        ],
    )
    orchestrator = JudgeOrchestrator.from_hub(hub)  # type: ignore[arg-type]
    result = orchestrator.judge(
        case_id="case_001",
        candidate_id="c1",
        original=original,
        candidate=candidate,
        target_card=card,
        declared_dimension="light_shadow",
        opponents=[OpponentCandidate(candidate_id="c2", image=opponent)],
    )
    assert result.redline.pass_ is True
    assert result.verdict_vs_original == Verdict.BETTER
    assert len(result.pairwise) == 2
    assert result.pairwise[0].bidirectional_agreed is True
    assert result.pairwise[1].result == Verdict.SAME
