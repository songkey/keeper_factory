from __future__ import annotations

from enum import StrEnum


class CaseCategory(StrEnum):
    BAD = "bad"
    GOOD = "good"
    REDLINE = "redline"


class ExperimentKind(StrEnum):
    MAIN = "main"
    VALIDATION = "validation"
    PROBE = "probe"
    WARMUP = "warmup"


class ExperimentStatus(StrEnum):
    COMPLETED = "completed"
    EXECUTION_FAILURE = "execution_failure"
    SKIPPED_DNR = "skipped_dnr"


class Verdict(StrEnum):
    BETTER = "better"
    SAME = "same"
    WORSE = "worse"


class KnowledgeType(StrEnum):
    CASE_RECIPE = "case_recipe"
    PATTERN_PATCH = "pattern_patch"
    FAILURE_NOTE = "failure_note"
    CAPABILITY_NOTE = "capability_note"


class KnowledgeStatus(StrEnum):
    CANDIDATE = "candidate"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    DISPUTED = "disputed"
    DEPRECATED = "deprecated"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LoopStage(StrEnum):
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4A = "f4a"
    F4B = "f4b"
    F4C = "f4c"
    F5 = "f5"
    BATCH_WAIT = "batch_wait"


class ValidationState(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    RESOLVED = "resolved"
