from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from keeper_factory.config import LoadedConfig
from keeper_factory.judge import JudgeOrchestrator
from keeper_factory.ledger import P1VersionChain, format_loop_dir, utc_now_iso
from keeper_factory.ledger.store import LedgerStore
from keeper_factory.loop.checkpoint import CheckpointDriftError, CheckpointLock, CheckpointStore
from keeper_factory.loop.stages import (
    LoopState,
    stage_batch_wait,
    stage_f1,
    stage_f2,
    stage_f3,
    stage_f4a,
    stage_f4b,
    stage_f4c,
    stage_f5,
)
from keeper_factory.memory.store import MemoryStore
from keeper_factory.models.hub import ModelHub
from keeper_factory.schemas import KnowledgeStatus, LoopStage
from keeper_factory.util.atomic_io import atomic_write_json
from keeper_factory.util.git_ops import git_commit_all, is_git_dirty

STAGE_ORDER: tuple[LoopStage, ...] = (
    LoopStage.F1,
    LoopStage.F2,
    LoopStage.F3,
    LoopStage.F4A,
    LoopStage.F4B,
    LoopStage.F4C,
    LoopStage.F5,
    LoopStage.BATCH_WAIT,
)


@dataclass(frozen=True)
class LoopRuntimeStatus:
    running: bool
    loop: int | None
    batch: int | None
    stage: str | None
    pending_review_count: int
    checkpoint_exists: bool


class LoopRuntime:
    def __init__(self, loaded: LoadedConfig, *, dry_run: bool = False) -> None:
        self.loaded = loaded
        self.dry_run = dry_run
        self.store = CheckpointStore(
            data_root=loaded.data_root,
            config_hash=loaded.config_hash,
            prompts_hash=loaded.prompts_hash,
        )
        self.lock = CheckpointLock(self.store.lock_path)
        self.ledger = LedgerStore(loaded.data_root)
        self.memory = MemoryStore(loaded.data_root)
        self.p1_chain = P1VersionChain(loaded.data_root)
        self.loops_root = loaded.data_root / "ledger" / "loops"
        self.loops_root.mkdir(parents=True, exist_ok=True)
        self.hub = ModelHub.from_loaded(loaded, dry_run=dry_run)
        self.judge = JudgeOrchestrator.from_hub(self.hub)

    def run(self, loops: int | None = None) -> list[int]:
        target = max(1, int(loops or 1))
        if self.store.load() is not None:
            raise RuntimeError("checkpoint exists; run `kf resume` instead")

        self.lock.acquire()
        completed: list[int] = []
        try:
            start = self._next_loop_number()
            for loop_no in range(start, start + target):
                batch = self._batch_for_loop(loop_no)
                self._run_single_loop(loop_no, batch=batch, start_stage=LoopStage.F1)
                completed.append(loop_no)
        finally:
            self.lock.release()
        return completed

    def resume(self, *, force: bool = False) -> int:
        checkpoint = self.store.load()
        if checkpoint is None:
            raise RuntimeError("no checkpoint found")

        self.store.assert_compatible(checkpoint, force=force)
        self.lock.acquire()
        try:
            try:
                dirty = is_git_dirty(self.loaded.data_root)
            except RuntimeError:
                dirty = False
            if dirty:
                git_commit_all(self.loaded.data_root, f"recovery: loop {checkpoint.loop}")
            self._run_single_loop(
                checkpoint.loop,
                batch=checkpoint.batch,
                start_stage=checkpoint.stage,
            )
            return checkpoint.loop
        finally:
            self.lock.release()

    def status(self) -> LoopRuntimeStatus:
        checkpoint = self.store.load()
        runtime_state = self.store.read_runtime_state() or {}
        pending_review_count = sum(
            1
            for item in self.memory.list_all()
            if item.status == KnowledgeStatus.PENDING_REVIEW
        )

        if checkpoint is not None:
            return LoopRuntimeStatus(
                running=True,
                loop=checkpoint.loop,
                batch=checkpoint.batch,
                stage=checkpoint.stage.value,
                pending_review_count=pending_review_count,
                checkpoint_exists=True,
            )

        return LoopRuntimeStatus(
            running=bool(runtime_state.get("running", False)),
            loop=runtime_state.get("loop") if isinstance(runtime_state.get("loop"), int) else None,
            batch=runtime_state.get("batch") if isinstance(runtime_state.get("batch"), int) else None,
            stage=runtime_state.get("stage") if isinstance(runtime_state.get("stage"), str) else None,
            pending_review_count=pending_review_count,
            checkpoint_exists=False,
        )

    def _run_single_loop(self, loop_no: int, *, batch: int, start_stage: LoopStage) -> None:
        state = self._load_or_init_state(loop_no=loop_no, batch=batch)
        stage_index = STAGE_ORDER.index(start_stage)
        f2_outputs: list[dict[str, object]] = []
        for stage in STAGE_ORDER[stage_index:]:
            self.store.save(loop=loop_no, batch=batch, stage=stage)
            state.stage_history.append(stage.value)
            if stage == LoopStage.F1:
                state = stage_f1(
                    loaded=self.loaded,
                    hub=self.hub,
                    state=state,
                    memory=self.memory,
                    p1_chain=self.p1_chain,
                )
            elif stage == LoopStage.F2:
                state, f2_outputs = stage_f2(
                    loaded=self.loaded,
                    hub=self.hub,
                    state=state,
                    p1_chain=self.p1_chain,
                )
            elif stage == LoopStage.F3:
                state, _records = stage_f3(
                    loaded=self.loaded,
                    hub=self.hub,
                    state=state,
                    ledger=self.ledger,
                    memory=self.memory,
                    judge=self.judge,
                    f2_outputs=f2_outputs,
                )
            elif stage == LoopStage.F4A:
                state = stage_f4a(state=state, memory=self.memory)
            elif stage == LoopStage.F4B:
                state = stage_f4b(state=state, memory=self.memory)
            elif stage == LoopStage.F4C:
                state = stage_f4c(
                    loaded=self.loaded,
                    hub=self.hub,
                    state=state,
                    p1_chain=self.p1_chain,
                )
            elif stage == LoopStage.F5:
                state = stage_f5(loaded=self.loaded, state=state)
            elif stage == LoopStage.BATCH_WAIT:
                state = stage_batch_wait(loaded=self.loaded, state=state, memory=self.memory)
            self._save_state(state)

        cost = self.hub.consume_cost()
        if cost is not None:
            self.ledger.append_budget(loop=loop_no, batch=batch, cost=cost)
        self._write_loop_summary(loop_no=loop_no, batch=batch, state=state)
        self._remove_state(loop_no)
        self.store.clear(loop=loop_no, batch=batch, stage=LoopStage.BATCH_WAIT)

    def _write_loop_summary(self, *, loop_no: int, batch: int, state: LoopState) -> Path:
        payload = state.to_json()
        payload.update(
            {
                "loop": loop_no,
                "batch": batch,
                "dry_run": self.dry_run,
                "created_at": utc_now_iso(),
            }
        )
        path = self.loops_root / f"{format_loop_dir(loop_no)}.json"
        atomic_write_json(path, payload)
        return path

    def _state_path(self, loop_no: int) -> Path:
        return self.loops_root / f"{format_loop_dir(loop_no)}.runtime.json"

    def _load_or_init_state(self, *, loop_no: int, batch: int) -> LoopState:
        path = self._state_path(loop_no)
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return LoopState.from_json(payload)
        return LoopState(loop=loop_no, batch=batch)

    def _save_state(self, state: LoopState) -> None:
        atomic_write_json(self._state_path(state.loop), state.to_json())

    def _remove_state(self, loop_no: int) -> None:
        self._state_path(loop_no).unlink(missing_ok=True)

    def _next_loop_number(self) -> int:
        existing = sorted(self.loops_root.glob("loop_*.json"))
        if not existing:
            return 1
        latest = existing[-1].stem.replace("loop_", "")
        try:
            return int(latest) + 1
        except ValueError:
            return 1

    def _batch_for_loop(self, loop_no: int) -> int:
        batch_size = self.loaded.config.loop.batch_size
        return ((loop_no - 1) // batch_size) + 1

