from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from keeper_factory.schemas.experiment import EnvInfo, ExperimentRecord, SignatureIndexEntry, StrategyInfo
from keeper_factory.schemas.enums import ExperimentStatus
from keeper_factory.util.hashing import canonical_json, sha256_prefix


@dataclass(frozen=True)
class SignatureInput:
    case_id: str
    declared_dimension: str
    strategy_digest: str
    injected_knowledge: list[str]
    env: EnvInfo


def compute_experiment_signature(
    *,
    case_id: str,
    declared_dimension: str,
    strategy_digest: str,
    injected_knowledge: list[str],
    env: EnvInfo,
) -> str:
    payload = {
        "case_id": case_id,
        "declared_dimension": declared_dimension,
        "strategy_digest": strategy_digest,
        "injected_knowledge": sorted(injected_knowledge),
        "env": env.model_dump(mode="json"),
    }
    return sha256_prefix(canonical_json(payload))


def signature_input_from_record(record: ExperimentRecord) -> SignatureInput:
    return SignatureInput(
        case_id=record.case_id,
        declared_dimension=record.strategy.declared_dimension,
        strategy_digest=record.strategy.strategy_digest,
        injected_knowledge=list(record.strategy.injected_knowledge),
        env=record.env,
    )


def should_index_for_dnr(record: ExperimentRecord) -> bool:
    """Only judged experiments enter do-not-repeat (LG4)."""
    return record.status == ExperimentStatus.COMPLETED


def signature_index_entry_from_record(record: ExperimentRecord) -> SignatureIndexEntry | None:
    if not should_index_for_dnr(record):
        return None
    verdict = None
    if record.judge_summary is not None:
        verdict = record.judge_summary.verdict_vs_original.value
    return SignatureIndexEntry(
        sig=record.exp_sig,
        exp_id=record.exp_id,
        verdict=verdict,
        loop=record.loop,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def format_loop_dir(loop: int) -> str:
    return f"loop_{loop:03d}"


def format_exp_id(*, loop: int, kind: str, suffix: str) -> str:
    return f"loop{loop:03d}_{kind}_{suffix}"
