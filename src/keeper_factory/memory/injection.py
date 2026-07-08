from __future__ import annotations

from dataclasses import dataclass, field

from keeper_factory.schemas.enums import CaseCategory, Confidence, KnowledgeStatus, KnowledgeType
from keeper_factory.schemas.knowledge import KnowledgeDocument


_STATUS_RANK = {
    KnowledgeStatus.ACTIVE: 0,
    KnowledgeStatus.CANDIDATE: 1,
    KnowledgeStatus.PENDING_REVIEW: 2,
    KnowledgeStatus.DISPUTED: 3,
}

_CONFIDENCE_RANK = {
    Confidence.HIGH: 0,
    Confidence.MEDIUM: 1,
    Confidence.LOW: 2,
}

_INJECTABLE_STATUSES = {
    KnowledgeStatus.ACTIVE,
    KnowledgeStatus.CANDIDATE,
    KnowledgeStatus.PENDING_REVIEW,
    KnowledgeStatus.DISPUTED,
}


@dataclass(frozen=True)
class InjectionItem:
    knowledge_id: str
    knowledge_type: KnowledgeType
    status: KnowledgeStatus
    disputed: bool
    pending_review: bool
    text: str


@dataclass
class InjectionSelection:
    failure_notes: list[InjectionItem] = field(default_factory=list)
    scoped_items: list[InjectionItem] = field(default_factory=list)

    @property
    def all_ids(self) -> list[str]:
        return [item.knowledge_id for item in (*self.failure_notes, *self.scoped_items)]


def _scope_matches(
    doc: KnowledgeDocument,
    *,
    dimensions: list[str],
    category: CaseCategory,
    image_class: str | None,
) -> bool:
    scope = doc.scope
    if scope.dimensions and not set(scope.dimensions).intersection(dimensions):
        return False
    if scope.categories and category not in scope.categories:
        return False
    if scope.image_class and image_class:
        if scope.image_class not in image_class and image_class not in scope.image_class:
            return False
    return True


def _injection_text(doc: KnowledgeDocument) -> str:
    if doc.type == KnowledgeType.FAILURE_NOTE:
        parts = [doc.failure_pattern or "", doc.avoid_rule or ""]
        return "\n".join(part for part in parts if part)
    if doc.type == KnowledgeType.PATTERN_PATCH:
        parts = [doc.principle or "", doc.prompt_fragment or ""]
        if doc.risk_note:
            parts.append(f"Risk: {doc.risk_note}")
        return "\n".join(part for part in parts if part)
    if doc.type == KnowledgeType.CAPABILITY_NOTE:
        parts = [doc.behavior or "", doc.workaround or ""]
        return "\n".join(part for part in parts if part)
    return ""


def _marker_prefix(doc: KnowledgeDocument) -> str:
    if doc.status == KnowledgeStatus.DISPUTED:
        return "[DISPUTED] "
    if doc.status == KnowledgeStatus.PENDING_REVIEW:
        return "[PENDING_REVIEW] "
    return ""


def select_injections(
    documents: list[KnowledgeDocument],
    *,
    dimensions: list[str],
    category: CaseCategory,
    image_class: str | None = None,
    max_scoped: int = 3,
) -> InjectionSelection:
    failure_notes: list[InjectionItem] = []
    scoped_candidates: list[KnowledgeDocument] = []

    for doc in documents:
        if doc.status not in _INJECTABLE_STATUSES:
            continue
        if doc.status == KnowledgeStatus.DEPRECATED:
            continue

        if doc.type == KnowledgeType.FAILURE_NOTE and doc.status == KnowledgeStatus.ACTIVE:
            text = _marker_prefix(doc) + _injection_text(doc)
            failure_notes.append(
                InjectionItem(
                    knowledge_id=doc.id,
                    knowledge_type=doc.type,
                    status=doc.status,
                    disputed=doc.status == KnowledgeStatus.DISPUTED,
                    pending_review=doc.status == KnowledgeStatus.PENDING_REVIEW,
                    text=text.strip(),
                )
            )
            continue

        if doc.type in {KnowledgeType.PATTERN_PATCH, KnowledgeType.CAPABILITY_NOTE}:
            if _scope_matches(doc, dimensions=dimensions, category=category, image_class=image_class):
                scoped_candidates.append(doc)

    scoped_candidates.sort(
        key=lambda doc: (
            _STATUS_RANK.get(doc.status, 99),
            _CONFIDENCE_RANK.get(doc.confidence, 99),
            doc.id,
        )
    )

    scoped_items: list[InjectionItem] = []
    for doc in scoped_candidates[: max(0, max_scoped)]:
        text = _marker_prefix(doc) + _injection_text(doc)
        scoped_items.append(
            InjectionItem(
                knowledge_id=doc.id,
                knowledge_type=doc.type,
                status=doc.status,
                disputed=doc.status == KnowledgeStatus.DISPUTED,
                pending_review=doc.status == KnowledgeStatus.PENDING_REVIEW,
                text=text.strip(),
            )
        )

    return InjectionSelection(failure_notes=failure_notes, scoped_items=scoped_items)
