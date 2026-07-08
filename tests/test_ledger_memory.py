from __future__ import annotations

from pathlib import Path

import pytest

from keeper_factory.ledger import LedgerStore, compute_experiment_signature
from keeper_factory.ledger.p1 import P1VersionChain
from keeper_factory.ledger.signatures import should_index_for_dnr
from keeper_factory.memory import MemoryStore, PromotionDecision, PromotionManager, select_injections
from keeper_factory.schemas.enums import (
    CaseCategory,
    Confidence,
    ExperimentKind,
    ExperimentStatus,
    KnowledgeStatus,
    KnowledgeType,
    ValidationState,
    Verdict,
)
from keeper_factory.schemas.experiment import (
    CallCounts,
    EnvInfo,
    ExecutionScores,
    ExperimentCost,
    ExperimentRecord,
    JudgeSummary,
    StrategyInfo,
    TokenUsageEntry,
)
from keeper_factory.schemas.knowledge import KnowledgeDocument, KnowledgeScope


def _env() -> EnvInfo:
    return EnvInfo(
        vlm="gpt-5.5",
        edit_model="gpt-image-2",
        judge_model="gpt-5.5",
        p1_hash="h1",
        redline_prompt_hash="h2",
        quality_prompt_hash="h3",
        dimension_vocab="dimension_vocab_v0",
        anchor_set="anchor_v0",
    )


def _sample_record(*, status: ExperimentStatus = ExperimentStatus.COMPLETED) -> ExperimentRecord:
    env = _env()
    strategy = StrategyInfo(
        p1_version="p1_v001",
        candidate_index=1,
        declared_dimension="light_shadow",
        strategy_digest="sha256:strategy",
        injected_knowledge=["pp_0001"],
    )
    sig = compute_experiment_signature(
        case_id="case_001",
        declared_dimension=strategy.declared_dimension,
        strategy_digest=strategy.strategy_digest,
        injected_knowledge=strategy.injected_knowledge,
        env=env,
    )
    judge_summary = None
    if status == ExperimentStatus.COMPLETED:
        judge_summary = JudgeSummary(
            redline_pass=True,
            verdict_vs_original=Verdict.BETTER,
            direction_score=3,
            execution_scores=ExecutionScores(
                realization=3, intensity=2, collateral_damage=4
            ),
        )
    return ExperimentRecord(
        exp_id="loop001_main_c1",
        exp_sig=sig,
        loop=1,
        batch=1,
        kind=ExperimentKind.MAIN,
        case_id="case_001",
        strategy=strategy,
        env=env,
        judge_summary=judge_summary,
        status=status,
        cost=ExperimentCost(
            calls=CallCounts(vlm=2, edit=1),
            tokens=[TokenUsageEntry(model="gpt-5.5", input=10, output=5)],
        ),
        created_at="2026-07-08T12:00:00+08:00",
    )


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "ledger" / "experiments").mkdir(parents=True)
    (root / "memory").mkdir(parents=True)
    return root


def test_compute_experiment_signature_stable() -> None:
    env = _env()
    sig1 = compute_experiment_signature(
        case_id="case_001",
        declared_dimension="light_shadow",
        strategy_digest="sha256:strategy",
        injected_knowledge=["pp_0002", "pp_0001"],
        env=env,
    )
    sig2 = compute_experiment_signature(
        case_id="case_001",
        declared_dimension="light_shadow",
        strategy_digest="sha256:strategy",
        injected_knowledge=["pp_0001", "pp_0002"],
        env=env,
    )
    assert sig1 == sig2
    assert sig1.startswith("sha256:")


def test_ledger_write_and_dnr(data_root: Path) -> None:
    store = LedgerStore(data_root)
    completed = _sample_record(status=ExperimentStatus.COMPLETED)
    failed = _sample_record(status=ExperimentStatus.EXECUTION_FAILURE)
    failed = failed.model_copy(update={"exp_id": "loop001_main_c2", "exp_sig": "sha256:other"})

    store.write_experiment(completed)
    store.write_experiment(failed)

    assert store.is_dnr(completed.exp_sig) is True
    assert store.is_dnr(failed.exp_sig) is False
    assert should_index_for_dnr(completed) is True
    assert should_index_for_dnr(failed) is False

    loaded = store.read_experiment("loop001_main_c1", loop=1)
    assert loaded is not None
    assert loaded.exp_id == "loop001_main_c1"


def test_ledger_rebuild_signatures(data_root: Path) -> None:
    store = LedgerStore(data_root)
    store.write_experiment(_sample_record())
    store.signatures_path.unlink()
    count = store.rebuild_signatures()
    assert count == 1
    assert store.is_dnr(_sample_record().exp_sig)


def test_p1_version_chain(data_root: Path) -> None:
    chain = P1VersionChain(data_root)
    version = chain.ensure_initial()
    assert version == "p1_v001"
    assert chain.current_version() == "p1_v001"


def test_memory_yaml_roundtrip(data_root: Path) -> None:
    store = MemoryStore(data_root)
    doc = KnowledgeDocument(
        id="fn_0001",
        type=KnowledgeType.FAILURE_NOTE,
        status=KnowledgeStatus.ACTIVE,
        created_loop=1,
        updated_loop=1,
        scope=KnowledgeScope(dimensions=["light_shadow"], categories=[CaseCategory.BAD]),
        confidence=Confidence.MEDIUM,
        failure_pattern="too many edit verbs",
        avoid_rule="single main instruction only",
        failure_tags=["full_repaint"],
    )
    store.save(doc)
    loaded = store.get("fn_0001")
    assert loaded is not None
    assert loaded.failure_pattern == doc.failure_pattern
    assert loaded.failure_tags == ["full_repaint"]


def test_injection_selection_rules(data_root: Path) -> None:
    store = MemoryStore(data_root)
    failure = KnowledgeDocument(
        id="fn_0001",
        type=KnowledgeType.FAILURE_NOTE,
        status=KnowledgeStatus.ACTIVE,
        created_loop=1,
        updated_loop=1,
        failure_pattern="pattern",
        avoid_rule="avoid",
    )
    patch = KnowledgeDocument(
        id="pp_0001",
        type=KnowledgeType.PATTERN_PATCH,
        status=KnowledgeStatus.CANDIDATE,
        created_loop=1,
        updated_loop=1,
        confidence=Confidence.HIGH,
        scope=KnowledgeScope(dimensions=["light_shadow"], categories=[CaseCategory.BAD]),
        principle="principle",
        prompt_fragment="fragment",
    )
    unrelated = KnowledgeDocument(
        id="pp_0002",
        type=KnowledgeType.PATTERN_PATCH,
        status=KnowledgeStatus.ACTIVE,
        created_loop=1,
        updated_loop=1,
        scope=KnowledgeScope(dimensions=["color_grading"]),
        principle="other",
        prompt_fragment="other",
    )
    store.save(failure)
    store.save(patch)
    store.save(unrelated)

    selection = select_injections(
        store.list_all(),
        dimensions=["light_shadow"],
        category=CaseCategory.BAD,
        max_scoped=3,
    )
    assert [item.knowledge_id for item in selection.failure_notes] == ["fn_0001"]
    assert [item.knowledge_id for item in selection.scoped_items] == ["pp_0001"]
    assert selection.all_ids == ["fn_0001", "pp_0001"]


def test_promotion_flow(data_root: Path) -> None:
    store = MemoryStore(data_root)
    manager = PromotionManager(store)
    doc = KnowledgeDocument(
        id="pp_0001",
        type=KnowledgeType.PATTERN_PATCH,
        status=KnowledgeStatus.CANDIDATE,
        created_loop=1,
        updated_loop=1,
        principle="p",
        prompt_fragment="f",
    )
    store.save(doc)
    manager.mark_pending_review(["pp_0001"], loop=2)
    result = manager.apply_decision("pp_0001", PromotionDecision.APPROVE, loop=2)
    assert result.new_status == KnowledgeStatus.ACTIVE
    assert store.get("pp_0001").confidence == Confidence.MEDIUM


def test_case_recipe_ttl_discard(data_root: Path) -> None:
    store = MemoryStore(data_root)
    manager = PromotionManager(store)
    doc = KnowledgeDocument(
        id="cr_0001",
        type=KnowledgeType.CASE_RECIPE,
        status=KnowledgeStatus.CANDIDATE,
        created_loop=1,
        updated_loop=1,
        case_id="case_001",
        declared_dimension="light_shadow",
        strategy_summary="summary",
        validation_state=ValidationState.PENDING,
        ttl_loops=2,
    )
    store.save(doc)
    discarded = manager.discard_expired_case_recipes(current_loop=4)
    assert discarded == ["cr_0001"]
    assert store.get("cr_0001").status == KnowledgeStatus.DEPRECATED
