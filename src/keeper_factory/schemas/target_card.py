from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import CaseCategory


class CandidateDimension(StrictModel):
    dimension: str
    hint: str | None = None


class TargetCard(StrictModel):
    case_id: str
    category: CaseCategory
    scene_brief: str
    candidate_dimensions: list[CandidateDimension] = Field(min_length=1, max_length=3)
    must_keep: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    problem_note: str | None = None
    established_note: str | None = None
    trap_note: str | None = None
    # Placeholder from `kf seed-demo`; excluded from real F.1 / F.4a pools when
    # non-demo cases exist (avoids image-edit hallucinating on gradient stubs).
    demo: bool = False

    @model_validator(mode="after")
    def validate_category_fields(self) -> Self:
        if self.category == CaseCategory.BAD and not self.problem_note:
            raise ValueError("problem_note is required for bad cases")
        if self.category == CaseCategory.GOOD and not self.established_note:
            raise ValueError("established_note is required for good cases")
        if self.category == CaseCategory.REDLINE and not self.trap_note:
            raise ValueError("trap_note is required for redline cases")
        return self
