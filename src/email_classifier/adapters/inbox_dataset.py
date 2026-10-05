"""Dataset-backed inbox source (email-ingestion spec: replaceable source).

Reads the JSON dataset schema defined in design.md (D6) and exposes
normalized ``EmailMessage`` items plus their frozen ``expected`` ground
truth. Ingestion is idempotent by ``message_id``; non-synthetic items are
rejected and reported, never silently skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from email_classifier.domain.models import (
    Attachment,
    AttachmentStatus,
    EmailMessage,
)

_STATUS_BY_VALUE = {s.value: s for s in AttachmentStatus}


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one ingest pass over the dataset."""

    ingested_count: int
    rejected: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


@dataclass
class InboxDatasetSource:
    """JSON dataset adapter implementing the ``EmailSource`` boundary."""

    emails: list[dict]
    _normalized: list[EmailMessage] = field(default_factory=list, init=False)
    _rejected: list[str] = field(default_factory=list, init=False)
    _ingested_ids: set[str] = field(default_factory=set, init=False)
    _expected: dict[str, dict] = field(default_factory=dict, init=False)

    @classmethod
    def from_file(cls, path: str | Path) -> InboxDatasetSource:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("emails"), list):
            raise ValueError(f"dataset file {path} must contain an 'emails' list")
        return cls(emails=data["emails"])

    def _normalize(self, item: dict) -> EmailMessage:
        attachments = tuple(
            Attachment(
                filename=att["filename"],
                mime=att["mime"],
                extracted_text=att.get("extracted_text"),
                status=_STATUS_BY_VALUE[att["status"]],
            )
            for att in item.get("attachments") or []
        )
        received_raw = item["received_at"]
        received_at = (
            received_raw
            if isinstance(received_raw, datetime)
            else datetime.fromisoformat(str(received_raw).replace("Z", "+00:00"))
        )
        return EmailMessage(
            message_id=item["message_id"],
            sender=item["sender"],
            recipients=list(item.get("recipients") or []),
            subject=item["subject"],
            body=item["body"],
            received_at=received_at,
            thread_id=item.get("thread_id"),
            attachments=attachments,
        )

    def _is_synthetic(self, item: dict) -> bool:
        # The dataset is fully synthetic by construction (D6); an item is
        # non-synthetic only when explicitly flagged as real content.
        return item.get("synthetic", True) is not False

    def list_emails(self) -> list[EmailMessage]:
        """Normalized intake: full dataset, including rejected items excluded.

        Only synthetic items are exposed through the source boundary;
        non-synthetic ones are recorded as rejected and reported on ingest.
        """
        if not self._normalized and not self._rejected:
            for item in self.emails:
                if self._is_synthetic(item):
                    self._normalized.append(self._normalize(item))
                    self._expected[item["message_id"]] = item.get("expected") or {}
                else:
                    self._rejected.append(item["message_id"])
        return list(self._normalized)

    def expected_for(self, message_id: str) -> dict:
        """Frozen ground-truth labels for a dataset email (D7)."""
        self.list_emails()  # ensure classification pass ran
        return self._expected.get(message_id, {})

    def ingest(self) -> IngestResult:
        """Idempotent ingest: each distinct message ingested at most once."""
        self.list_emails()  # normalize + classify rejected items first
        newly_ingested = 0
        for email in self._normalized:
            if email.message_id in self._ingested_ids:
                continue  # replay: no duplicate, no reclassification
            self._ingested_ids.add(email.message_id)
            newly_ingested += 1
        return IngestResult(
            ingested_count=newly_ingested, rejected=tuple(self._rejected)
        )

    def seen_message_ids(self) -> set[str]:
        return set(self._ingested_ids)
