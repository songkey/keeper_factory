from __future__ import annotations

import re
from pathlib import Path

from keeper_factory.schemas.enums import KnowledgeType

_ID_RE = re.compile(r"^([a-z]{2})_(\d+)$")

TYPE_PREFIX: dict[KnowledgeType, str] = {
    KnowledgeType.CASE_RECIPE: "cr",
    KnowledgeType.PATTERN_PATCH: "pp",
    KnowledgeType.FAILURE_NOTE: "fn",
    KnowledgeType.CAPABILITY_NOTE: "cn",
}

PREFIX_TYPE: dict[str, KnowledgeType] = {v: k for k, v in TYPE_PREFIX.items()}


def knowledge_type_from_id(knowledge_id: str) -> KnowledgeType:
    match = _ID_RE.match(knowledge_id)
    if not match:
        raise ValueError(f"invalid knowledge id: {knowledge_id}")
    prefix = match.group(1)
    if prefix not in PREFIX_TYPE:
        raise ValueError(f"unknown knowledge id prefix: {prefix}")
    return PREFIX_TYPE[prefix]


def next_knowledge_id(existing_ids: list[str], knowledge_type: KnowledgeType) -> str:
    prefix = TYPE_PREFIX[knowledge_type]
    max_num = 0
    for item in existing_ids:
        match = _ID_RE.match(item)
        if match and match.group(1) == prefix:
            max_num = max(max_num, int(match.group(2)))
    return f"{prefix}_{max_num + 1:04d}"
