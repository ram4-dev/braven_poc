"""Engine-neutral boundary Protocols (jev-scoring §A: anti-corruption boundary).

Adapters implement these ports; the domain never imports adapter modules.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from email_classifier.domain.models import (
    Decision,
    EmailMessage,
    QuestionSet,
    ScoreResult,
)

__all__ = [
    "AttachmentExtractor",
    "ClassificationRepository",
    "EmailSource",
    "ScoringEngine",
]


@runtime_checkable
class EmailSource(Protocol):
    """Replaceable inbox source boundary (email-ingestion: replaceable source)."""

    def list_emails(self) -> list[EmailMessage]: ...


@runtime_checkable
class ScoringEngine(Protocol):
    """Engine-neutral scoring boundary: one probability per question, fail-closed."""

    def score(self, email: EmailMessage, questions: QuestionSet) -> ScoreResult:
        """Raise ScoreError on any engine failure; never fabricate scores."""
        ...


@runtime_checkable
class ClassificationRepository(Protocol):
    """Append-only storage boundary (classification-storage spec)."""

    def append_email(self, email: EmailMessage, source: str) -> str: ...

    def append_classified(self, email_id: str, decision: Decision) -> str: ...

    def append_failed(self, email_id: str, decision: Decision) -> str: ...


@runtime_checkable
class AttachmentExtractor(Protocol):
    """Attachment text extraction boundary with explicit extraction status."""

    def extract(self, email: EmailMessage) -> EmailMessage: ...
