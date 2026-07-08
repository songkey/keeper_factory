from __future__ import annotations

from pydantic import Field

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import LoopStage


class CheckpointInflight(StrictModel):
    main_case_id: str | None = None
    candidates_total: int = 0
    candidates_done: list[str] = Field(default_factory=list)
    validating_recipe: str | None = None


class Checkpoint(StrictModel):
    loop: int
    batch: int
    stage: LoopStage
    inflight: CheckpointInflight = Field(default_factory=CheckpointInflight)
    config_hash: str
    prompts_hash: str
    updated_at: str
