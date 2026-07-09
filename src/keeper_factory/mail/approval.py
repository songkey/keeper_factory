from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from keeper_factory.memory import MemoryStore, PromotionManager
from keeper_factory.memory.promotion import PromotionDecision
from keeper_factory.schemas import KnowledgeStatus


@dataclass(frozen=True)
class ApprovalLine:
    knowledge_id: str
    decision: PromotionDecision


_LINE_RE = re.compile(
    r"^\s*(?P<id>[a-z]{2}_\d{4})\s*:\s*(?P<decision>approve|reject|dispute|ok|no|hold)\s*$",
    re.IGNORECASE,
)
_SHORT_RE = re.compile(
    r"^\s*(?P<index>\d+)\s+(?P<decision>ok|no|hold|approve|reject|dispute)\s*$",
    re.IGNORECASE,
)


def parse_approval_text(text: str) -> list[ApprovalLine]:
    lines: list[ApprovalLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower() == "all ok":
            continue
        match = _LINE_RE.match(line)
        if match:
            lines.append(
                ApprovalLine(
                    knowledge_id=match.group("id").lower(),
                    decision=_normalize_decision(match.group("decision")),
                )
            )
    return lines


def parse_approval_with_batch(
    text: str,
    *,
    batch_path: Path,
) -> list[ApprovalLine]:
    explicit = parse_approval_text(text)
    if explicit:
        return explicit

    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    index_map = {
        int(item["index"]): item["knowledge_id"]
        for item in payload.get("pending_items", [])
        if "index" in item and "knowledge_id" in item
    }
    if "all ok" in text.lower():
        items = [
            ApprovalLine(knowledge_id=item["knowledge_id"], decision=PromotionDecision.APPROVE)
            for item in payload.get("pending_items", [])
            if "knowledge_id" in item
        ]
        if items:
            return items
        # Fallback when batch file was overwritten empty after a failed mail resume.
        return []

    resolved: list[ApprovalLine] = []
    for raw in text.splitlines():
        match = _SHORT_RE.match(raw.strip())
        if not match:
            continue
        kid = index_map.get(int(match.group("index")))
        if kid:
            resolved.append(
                ApprovalLine(
                    knowledge_id=kid,
                    decision=_normalize_decision(match.group("decision")),
                )
            )
    return resolved


def _normalize_decision(value: str) -> PromotionDecision:
    token = value.lower()
    if token in {"approve", "ok", "yes"}:
        return PromotionDecision.APPROVE
    if token in {"reject", "no"}:
        return PromotionDecision.REJECT
    return PromotionDecision.DISPUTE


def apply_approvals(
    *,
    memory: MemoryStore,
    approvals: list[ApprovalLine],
    loop: int,
) -> list[str]:
    manager = PromotionManager(memory)
    applied: list[str] = []
    for item in approvals:
        manager.apply_decision(item.knowledge_id, item.decision, loop=loop)
        applied.append(f"{item.knowledge_id}: {item.decision.value}")
    return applied


def clear_batch_approval(data_root: Path, *, batch: int) -> None:
    path = data_root / "ledger" / "batches" / f"batch_{batch:03d}.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["awaiting_approval"] = False
    payload["decisions"] = payload.get("decisions", [])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_awaiting_batch(data_root: Path) -> int | None:
    batches_dir = data_root / "ledger" / "batches"
    if not batches_dir.is_dir():
        return None
    for path in sorted(batches_dir.glob("batch_*.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("awaiting_approval"):
            return int(payload["batch"])
    return None


def count_pending_review(memory: MemoryStore) -> int:
    return sum(
        1 for item in memory.list_all() if item.status == KnowledgeStatus.PENDING_REVIEW
    )
