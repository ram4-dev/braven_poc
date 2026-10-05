"""Pure domain models: frozen dataclasses and frozen label enums. Zero I/O."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class Band(enum.StrEnum):
    """Canonical classification bands (PROD.md §11 vocabulary; never a label)."""

    AUTOMATIC = "AUTOMATIC"
    UNCERTAIN = "UNCERTAIN"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class AttachmentStatus(enum.StrEnum):
    EXTRACTED = "extracted"
    NOT_TEXT_EXTRACTABLE = "not_text_extractable"
    FAILED = "failed"


class PrimaryCategory(enum.StrEnum):
    NEW_LEAD = "NEW_LEAD"
    QUOTE_REQUEST = "QUOTE_REQUEST"
    NEW_POLICY = "NEW_POLICY"
    POLICY_RENEWAL = "POLICY_RENEWAL"
    POLICY_CHANGE = "POLICY_CHANGE"
    POLICY_CANCELLATION = "POLICY_CANCELLATION"
    CLAIM_NEW = "CLAIM_NEW"
    CLAIM_UPDATE = "CLAIM_UPDATE"
    CLAIM_DOCUMENTATION = "CLAIM_DOCUMENTATION"
    PAYMENT_BILLING = "PAYMENT_BILLING"
    COMPLAINT = "COMPLAINT"
    FRAUD_SUSPICION = "FRAUD_SUSPICION"
    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    PARTNERSHIP = "PARTNERSHIP"
    OTHER = "OTHER"


class Sensitivity(enum.StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    HIGHLY_CONFIDENTIAL = "HIGHLY_CONFIDENTIAL"
    PERSONAL_DATA = "PERSONAL_DATA"
    SENSITIVE_PERSONAL_DATA = "SENSITIVE_PERSONAL_DATA"


class Action(enum.StrEnum):
    NO_ACTION = "NO_ACTION"
    REPLY_REQUIRED = "REPLY_REQUIRED"
    DOCUMENT_REQUIRED = "DOCUMENT_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ESCALATE = "ESCALATE"
    URGENT = "URGENT"


class Priority(enum.StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Frozen label sets (taxonomy_mvp), for validation against configuration.
PRIMARY_CATEGORY_LABELS: list[str] = [m.value for m in PrimaryCategory]
SENSITIVITY_LABELS: list[str] = [m.value for m in Sensitivity]
ACTION_LABELS: list[str] = [m.value for m in Action]
PRIORITY_LABELS: list[str] = [m.value for m in Priority]

# Deferred categories are defined in PROD.md but MUST NOT be emitted in the MVP.
DEFERRED_CATEGORY_LABELS: list[str] = [
    "CLAIM_PAYMENT",
    "CLAIM_REJECTION",
    "UNDERWRITING",
    "BROKER_AGENT",
    "REINSURANCE",
    "SUPPLIER",
]


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime: str
    extracted_text: str | None
    status: AttachmentStatus


@dataclass(frozen=True)
class EmailMessage:
    """Normalized email intake (email-ingestion spec: normalized intake)."""

    message_id: str
    sender: str
    recipients: list[str]
    subject: str
    body: str
    received_at: datetime
    thread_id: str | None = None
    attachments: tuple[Attachment, ...] = field(default=())


@dataclass(frozen=True)
class Question:
    """One binary decision question fed to the engine (versioned config shape)."""

    question_id: str
    type: str
    instructions: str
    criteria_true: str
    criteria_false: str


@dataclass(frozen=True)
class QuestionSet:
    version: str
    questions: tuple[Question, ...]

    def by_id(self, question_id: str) -> Question:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        raise KeyError(question_id)


@dataclass(frozen=True)
class ScoreResult:
    """One probability per question, verbatim, plus scoring provenance."""

    scores: dict[str, float]
    engine_version: str
    question_set_version: str
    engine_request_id: str | None = None


class ScoreError(Exception):
    """Fail-closed scoring failure: no label, band or confidence is fabricated."""


@dataclass(frozen=True)
class LabelThreshold:
    dimension: str
    label: str
    auto_threshold: float
    review_floor: float


@dataclass(frozen=True)
class ThresholdConfig:
    """Versioned threshold table (configuration, never hardcoded in decisions)."""

    default_auto_threshold: float
    default_review_floor: float
    elevated: dict[str, LabelThreshold]
    version: str = "th-mvp"

    @staticmethod
    def mvp() -> ThresholdConfig:
        """The MVP table: default 0.90/0.65; elevated 0.95/0.40 for sensitive tiers."""
        elevated = {
            f"{t.dimension}/{t.label}": t
            for t in (
                LabelThreshold("primary_category", "FRAUD_SUSPICION", 0.95, 0.40),
                LabelThreshold("primary_category", "LEGAL", 0.95, 0.40),
                LabelThreshold("sensitivity", "HIGHLY_CONFIDENTIAL", 0.95, 0.40),
            )
        }
        return ThresholdConfig(
            default_auto_threshold=0.90,
            default_review_floor=0.65,
            elevated=elevated,
            version="th-mvp",
        )


@dataclass(frozen=True)
class Decision:
    """The full rules-engine output for one email (pure; no I/O, no engine access)."""

    status: str  # "CLASSIFIED" | "FAILED" | "REPLAYED"
    classifier_version: str
    engine_version: str
    question_set_version: str
    threshold_set_version: str
    raw_scores: dict[str, float]
    confidence: float | None
    band: Band | None
    requires_human_review: bool
    primary_category: PrimaryCategory | None
    secondary_categories: tuple[PrimaryCategory, ...]
    sensitivity: tuple[Sensitivity, ...]
    actions: tuple[Action, ...]
    priority: Priority | None
    queue_reason: str | None
