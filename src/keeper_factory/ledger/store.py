from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.experiment import ExperimentCost, ExperimentRecord, SignatureIndexEntry
from keeper_factory.ledger.signatures import (
    format_loop_dir,
    signature_index_entry_from_record,
    utc_now_iso,
)
from keeper_factory.util.atomic_io import append_jsonl, atomic_write_json


class BudgetEntry(StrictModel):
    loop: int
    batch: int
    cost: ExperimentCost
    created_at: str


class LedgerStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.ledger_root = data_root / "ledger"
        self.experiments_root = self.ledger_root / "experiments"
        self.signatures_path = self.ledger_root / "signatures.jsonl"
        self.budget_path = self.ledger_root / "budget.jsonl"

    def experiment_path(self, record: ExperimentRecord) -> Path:
        loop_dir = self.experiments_root / format_loop_dir(record.loop)
        return loop_dir / f"{record.exp_id}.json"

    def write_experiment(self, record: ExperimentRecord) -> Path:
        path = self.experiment_path(record)
        atomic_write_json(path, record.model_dump(mode="json"))
        entry = signature_index_entry_from_record(record)
        if entry is not None:
            self._append_signature(entry)
        return path

    def read_experiment(self, exp_id: str, *, loop: int | None = None) -> ExperimentRecord | None:
        if loop is not None:
            path = self.experiments_root / format_loop_dir(loop) / f"{exp_id}.json"
            if path.is_file():
                return ExperimentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            return None
        for path in sorted(self.experiments_root.glob("**/")):
            candidate = path / f"{exp_id}.json"
            if candidate.is_file():
                return ExperimentRecord.model_validate_json(candidate.read_text(encoding="utf-8"))
        return None

    def list_experiments(self, loop: int | None = None) -> list[ExperimentRecord]:
        if loop is not None:
            paths = sorted((self.experiments_root / format_loop_dir(loop)).glob("*.json"))
        else:
            paths = sorted(self.experiments_root.glob("**/*.json"))
        return [
            ExperimentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in paths
        ]

    def _append_signature(self, entry: SignatureIndexEntry) -> None:
        append_jsonl(self.signatures_path, entry.model_dump(mode="json"))

    def load_signatures(self) -> dict[str, SignatureIndexEntry]:
        if not self.signatures_path.is_file():
            return {}
        index: dict[str, SignatureIndexEntry] = {}
        for line in self.signatures_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = SignatureIndexEntry.model_validate(json.loads(line))
            index[entry.sig] = entry
        return index

    def is_dnr(self, exp_sig: str) -> bool:
        return exp_sig in self.load_signatures()

    def rebuild_signatures(self) -> int:
        entries: dict[str, SignatureIndexEntry] = {}
        for record in self.list_experiments():
            entry = signature_index_entry_from_record(record)
            if entry is not None:
                entries[entry.sig] = entry
        if self.signatures_path.exists():
            self.signatures_path.unlink()
        for entry in entries.values():
            self._append_signature(entry)
        return len(entries)

    def append_budget(self, *, loop: int, batch: int, cost: ExperimentCost) -> None:
        entry = BudgetEntry(loop=loop, batch=batch, cost=cost, created_at=utc_now_iso())
        append_jsonl(self.budget_path, entry.model_dump(mode="json"))

    def list_budget(self) -> list[BudgetEntry]:
        if not self.budget_path.is_file():
            return []
        rows: list[BudgetEntry] = []
        for line in self.budget_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(BudgetEntry.model_validate(json.loads(line)))
        return rows
