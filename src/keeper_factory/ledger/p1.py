from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from keeper_factory.schemas.base import StrictModel
from keeper_factory.util.atomic_io import atomic_write_text


class P1SlotDiff(StrictModel):
    slot: str
    before_hash: str
    after_hash: str
    diff_text: str


class P1VersionRecord(StrictModel):
    version: str
    parent: str | None = None
    created_loop: int
    slot_diffs: list[P1SlotDiff] = Field(default_factory=list)
    rationale: str
    refine_exp_ref: str | None = None


class P1VersionChain:
    CURRENT_FILE = "CURRENT"

    def __init__(self, data_root: Path) -> None:
        self.root = data_root / "ledger" / "p1_versions"
        self.root.mkdir(parents=True, exist_ok=True)

    def current_version(self) -> str | None:
        pointer = self.root / self.CURRENT_FILE
        if not pointer.is_file():
            return None
        value = pointer.read_text(encoding="utf-8").strip()
        return value or None

    def set_current_version(self, version: str) -> None:
        atomic_write_text(self.root / self.CURRENT_FILE, version + "\n")

    def version_path(self, version: str) -> Path:
        return self.root / f"{version}.yaml"

    def read_version(self, version: str) -> P1VersionRecord | None:
        path = self.version_path(version)
        if not path.is_file():
            return None
        from keeper_factory.memory.yaml_io import load_yaml_dict

        return P1VersionRecord.model_validate(load_yaml_dict(path))

    def write_version(self, record: P1VersionRecord) -> Path:
        from keeper_factory.memory.yaml_io import dump_yaml_dict

        path = self.version_path(record.version)
        dump_yaml_dict(path, record.model_dump(mode="json", exclude_none=True))
        return path

    def ensure_initial(self, *, version: str = "p1_v001", created_loop: int = 0) -> str:
        current = self.current_version()
        if current:
            return current
        record = P1VersionRecord(
            version=version,
            parent=None,
            created_loop=created_loop,
            rationale="initial P.1 bootstrap",
        )
        self.write_version(record)
        self.set_current_version(version)
        return version
