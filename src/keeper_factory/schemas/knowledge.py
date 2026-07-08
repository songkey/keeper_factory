from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator

from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import (
    CaseCategory,
    Confidence,
    KnowledgeStatus,
    KnowledgeType,
    ValidationState,
)


class KnowledgeScope(StrictModel):
    dimensions: list[str] = Field(default_factory=list)
    categories: list[CaseCategory] = Field(default_factory=list)
    image_class: str | None = None


class KnowledgeLineage(StrictModel):
    derived_from: str | None = None
    merged_from: list[str] = Field(default_factory=list)


class KnowledgeDocument(StrictModel):
    """Flat YAML document: envelope + type-specific payload in one file."""

    id: str
    type: KnowledgeType
    status: KnowledgeStatus
    created_loop: int
    updated_loop: int
    scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    confidence: Confidence = Confidence.LOW
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    lineage: KnowledgeLineage = Field(default_factory=KnowledgeLineage)

    # K.1 Case Recipe
    case_id: str | None = None
    declared_dimension: str | None = None
    strategy_summary: str | None = None
    p1_variant_ref: str | None = None
    judge_result_ref: str | None = None
    validation_state: ValidationState | None = None
    ttl_loops: int | None = None

    # K.2 Pattern Patch
    principle: str | None = None
    prompt_fragment: str | None = None
    risk_note: str | None = None

    # K.3 Failure Note
    failure_pattern: str | None = None
    trigger_conditions: str | None = None
    failure_tags: list[str] = Field(default_factory=list)
    avoid_rule: str | None = None

    # K.4 Capability Note
    model: str | None = None
    behavior: str | None = None
    reproductions: list[str] = Field(default_factory=list)
    workaround: str | None = None

    @model_validator(mode="after")
    def validate_type_payload(self) -> Self:
        if self.type == KnowledgeType.CASE_RECIPE:
            required = {
                "case_id": self.case_id,
                "declared_dimension": self.declared_dimension,
                "strategy_summary": self.strategy_summary,
                "validation_state": self.validation_state,
                "ttl_loops": self.ttl_loops,
            }
        elif self.type == KnowledgeType.PATTERN_PATCH:
            required = {
                "principle": self.principle,
                "prompt_fragment": self.prompt_fragment,
            }
        elif self.type == KnowledgeType.FAILURE_NOTE:
            required = {
                "failure_pattern": self.failure_pattern,
                "avoid_rule": self.avoid_rule,
            }
        elif self.type == KnowledgeType.CAPABILITY_NOTE:
            required = {
                "model": self.model,
                "behavior": self.behavior,
                "workaround": self.workaround,
            }
        else:
            return self

        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"{self.type.value} missing required fields: {', '.join(missing)}")
        return self

    def to_yaml_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude_none=True)
        if not self.failure_tags:
            data.pop("failure_tags", None)
        if not self.reproductions:
            data.pop("reproductions", None)
        if not self.evidence:
            data.pop("evidence", None)
        if not self.counter_evidence:
            data.pop("counter_evidence", None)
        if not self.lineage.merged_from and not self.lineage.derived_from:
            data.pop("lineage", None)
        elif not self.lineage.merged_from:
            data["lineage"] = {"derived_from": self.lineage.derived_from}
        return data

    @classmethod
    def from_yaml_dict(cls, data: dict[str, Any]) -> KnowledgeDocument:
        lineage = data.get("lineage") or {}
        if isinstance(lineage, dict):
            data = dict(data)
            data["lineage"] = KnowledgeLineage.model_validate(lineage)
        scope = data.get("scope") or {}
        if isinstance(scope, dict):
            data["scope"] = KnowledgeScope.model_validate(scope)
        return cls.model_validate(data)


# Backward-compatible aliases used by earlier step-1 schemas.
class KnowledgeEnvelope(KnowledgeDocument):
    pass


class CaseRecipeBody(StrictModel):
    case_id: str
    declared_dimension: str
    recipe_text: str


class PatternPatchBody(StrictModel):
    patch_text: str
    applies_when: str | None = None


class FailureNoteBody(StrictModel):
    failure_tag: str
    note_text: str


class CapabilityNoteBody(StrictModel):
    capability: str
    note_text: str
