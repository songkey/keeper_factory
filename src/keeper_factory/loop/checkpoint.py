from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from keeper_factory.ledger.signatures import utc_now_iso
from keeper_factory.schemas import Checkpoint, CheckpointInflight, LoopStage
from keeper_factory.util.atomic_io import atomic_write_json


class CheckpointDriftError(RuntimeError):
    pass


class CheckpointLockError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckpointStore:
    data_root: Path
    config_hash: str
    prompts_hash: str

    @property
    def path(self) -> Path:
        return self.data_root / "ledger" / "checkpoint.json"

    @property
    def runtime_state_path(self) -> Path:
        return self.data_root / "ledger" / "runtime_state.json"

    @property
    def lock_path(self) -> Path:
        return self.data_root / "ledger" / ".lock"

    def load(self) -> Checkpoint | None:
        if not self.path.is_file():
            return None
        return Checkpoint.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(
        self,
        *,
        loop: int,
        batch: int,
        stage: LoopStage,
        inflight: CheckpointInflight | None = None,
    ) -> Checkpoint:
        checkpoint = Checkpoint(
            loop=loop,
            batch=batch,
            stage=stage,
            inflight=inflight or CheckpointInflight(),
            config_hash=self.config_hash,
            prompts_hash=self.prompts_hash,
            updated_at=utc_now_iso(),
        )
        atomic_write_json(self.path, checkpoint.model_dump(mode="json"))
        self.write_runtime_state(loop=loop, batch=batch, stage=stage, running=True)
        return checkpoint

    def clear(self, *, loop: int, batch: int, stage: LoopStage) -> None:
        if self.path.exists():
            self.path.unlink(missing_ok=True)
        existing = self.read_runtime_state() or {}
        awaiting = bool(existing.get("awaiting_approval"))
        pending_batch = existing.get("pending_batch")
        pending_batch_int = int(pending_batch) if isinstance(pending_batch, int) else None
        self.write_runtime_state(
            loop=loop,
            batch=batch,
            stage=stage,
            running=False,
            awaiting_approval=awaiting,
            pending_batch=pending_batch_int,
        )

    def assert_compatible(self, checkpoint: Checkpoint, *, force: bool = False) -> None:
        if force:
            return
        if checkpoint.config_hash != self.config_hash:
            raise CheckpointDriftError("config hash drift detected; use --force to resume")
        if checkpoint.prompts_hash != self.prompts_hash:
            raise CheckpointDriftError("prompts hash drift detected; use --force to resume")

    def write_runtime_state(
        self,
        *,
        loop: int,
        batch: int,
        stage: LoopStage,
        running: bool,
        awaiting_approval: bool = False,
        pending_batch: int | None = None,
    ) -> None:
        payload = {
            "loop": loop,
            "batch": batch,
            "stage": stage.value,
            "running": running,
            "awaiting_approval": awaiting_approval,
            "updated_at": utc_now_iso(),
        }
        if pending_batch is not None:
            payload["pending_batch"] = pending_batch
        atomic_write_json(self.runtime_state_path, payload)

    def set_awaiting_approval(self, *, batch: int, loop: int) -> None:
        payload = self.read_runtime_state() or {}
        payload.update(
            {
                "loop": loop,
                "batch": batch,
                "stage": LoopStage.BATCH_WAIT.value,
                "running": False,
                "awaiting_approval": True,
                "pending_batch": batch,
                "updated_at": utc_now_iso(),
            }
        )
        atomic_write_json(self.runtime_state_path, payload)

    def clear_awaiting_approval(self) -> None:
        payload = self.read_runtime_state() or {}
        payload["awaiting_approval"] = False
        payload["pending_batch"] = None
        payload["updated_at"] = utc_now_iso()
        atomic_write_json(self.runtime_state_path, payload)

    def is_awaiting_approval(self) -> bool:
        payload = self.read_runtime_state() or {}
        return bool(payload.get("awaiting_approval"))

    def read_runtime_state(self) -> dict[str, object] | None:
        if not self.runtime_state_path.is_file():
            return None
        return json.loads(self.runtime_state_path.read_text(encoding="utf-8"))


@dataclass
class CheckpointLock:
    path: Path

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            payload = self._read_payload()
            pid = int(payload.get("pid") or 0)
            if pid and self._pid_alive(pid):
                raise CheckpointLockError(f"loop is already running (pid={pid})")
            self.path.unlink(missing_ok=True)

        payload = {"pid": os.getpid(), "created_at": utc_now_iso()}
        atomic_write_json(self.path, payload)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def _read_payload(self) -> dict[str, object]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

