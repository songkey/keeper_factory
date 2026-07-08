from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from keeper_factory.memory.store import MemoryStore
from keeper_factory.schemas.enums import Confidence, KnowledgeStatus, KnowledgeType
from keeper_factory.schemas.knowledge import KnowledgeDocument


class PromotionDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DISPUTE = "dispute"


@dataclass(frozen=True)
class PromotionResult:
    knowledge_id: str
    old_status: KnowledgeStatus
    new_status: KnowledgeStatus


def _bump_confidence(current: Confidence) -> Confidence:
    if current == Confidence.LOW:
        return Confidence.MEDIUM
    if current == Confidence.MEDIUM:
        return Confidence.HIGH
    return Confidence.HIGH


def _drop_confidence(current: Confidence) -> Confidence:
    if current == Confidence.HIGH:
        return Confidence.MEDIUM
    if current == Confidence.MEDIUM:
        return Confidence.LOW
    return Confidence.LOW


class PromotionManager:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def promote_to_candidate(self, knowledge_id: str, *, loop: int) -> PromotionResult:
        doc = self._require(knowledge_id)
        old = doc.status
        doc.status = KnowledgeStatus.CANDIDATE
        doc.updated_loop = loop
        if doc.confidence == Confidence.LOW:
            doc.confidence = Confidence.MEDIUM
        self.store.save(doc)
        return PromotionResult(knowledge_id, old, doc.status)

    def mark_pending_review(self, knowledge_ids: list[str], *, loop: int) -> list[PromotionResult]:
        results: list[PromotionResult] = []
        for knowledge_id in knowledge_ids:
            doc = self.store.get(knowledge_id)
            if doc is None or doc.status != KnowledgeStatus.CANDIDATE:
                continue
            old = doc.status
            doc.status = KnowledgeStatus.PENDING_REVIEW
            doc.updated_loop = loop
            self.store.save(doc)
            results.append(PromotionResult(knowledge_id, old, doc.status))
        return results

    def apply_decision(
        self,
        knowledge_id: str,
        decision: PromotionDecision,
        *,
        loop: int,
    ) -> PromotionResult:
        doc = self._require(knowledge_id)
        old = doc.status
        if decision == PromotionDecision.APPROVE:
            doc.status = KnowledgeStatus.ACTIVE
            doc.confidence = _bump_confidence(doc.confidence)
        elif decision == PromotionDecision.REJECT:
            doc.status = KnowledgeStatus.DEPRECATED
        else:
            doc.status = KnowledgeStatus.DISPUTED
            doc.confidence = _drop_confidence(doc.confidence)
        doc.updated_loop = loop
        self.store.save(doc)
        return PromotionResult(knowledge_id, old, doc.status)

    def discard_expired_case_recipes(self, *, current_loop: int) -> list[str]:
        discarded: list[str] = []
        for doc in self.store.list_all(KnowledgeType.CASE_RECIPE):
            if doc.ttl_loops is None:
                continue
            expires_at = doc.created_loop + doc.ttl_loops
            if current_loop > expires_at and doc.status not in {
                KnowledgeStatus.DEPRECATED,
                KnowledgeStatus.ACTIVE,
            }:
                doc.status = KnowledgeStatus.DEPRECATED
                doc.updated_loop = current_loop
                self.store.save(doc)
                discarded.append(doc.id)
        return discarded

    def _require(self, knowledge_id: str) -> KnowledgeDocument:
        doc = self.store.get(knowledge_id)
        if doc is None:
            raise KeyError(f"knowledge not found: {knowledge_id}")
        return doc
