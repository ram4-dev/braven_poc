"""Append-only SQLite repository (classification-storage spec) + review persistence.

Storage design (D5): every classification is an immutable append; the current
view of an email is its most recent record. Review corrections live in
``human_reviews``/``human_review_deltas`` and never mutate a classification.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from email_classifier.domain.models import (
    Action,
    Band,
    Decision,
    EmailMessage,
    PrimaryCategory,
    Priority,
    Sensitivity,
    ThresholdConfig,
)

_DDL = """
CREATE TABLE emails (
    email_id TEXT PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    thread_id TEXT,
    sender TEXT,
    recipients TEXT,
    subject TEXT,
    body TEXT,
    received_at TEXT,
    ingested_at TEXT,
    source TEXT,
    raw_ref TEXT
);
CREATE TABLE email_attachments (
    attachment_id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(email_id),
    filename TEXT,
    mime TEXT,
    extracted_text TEXT,
    extraction_status TEXT CHECK(extraction_status IN
        ('extracted', 'not_text_extractable', 'failed'))
);
CREATE TABLE classifications (
    classification_id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(email_id),
    status TEXT CHECK(status IN ('CLASSIFIED', 'FAILED', 'REPLAYED')),
    classifier_version TEXT NOT NULL,
    engine_version TEXT,
    question_set_version TEXT,
    threshold_set_version TEXT,
    raw_scores TEXT NOT NULL,
    engine_request_id TEXT,
    confidence REAL,
    classification_band TEXT CHECK(classification_band IN
        ('AUTOMATIC', 'UNCERTAIN', 'HUMAN_REVIEW')),
    requires_human_review INTEGER,
    primary_category TEXT,
    secondary_categories TEXT,
    sensitivity TEXT,
    actions TEXT,
    priority TEXT,
    received_at TEXT,
    ingested_at TEXT,
    scored_at TEXT,
    classified_at TEXT,
    source_classification_id TEXT,
    queue_reason TEXT
);
CREATE TABLE classification_labels (
    label_id TEXT PRIMARY KEY,
    classification_id TEXT NOT NULL REFERENCES classifications(classification_id),
    dimension TEXT,
    label TEXT,
    score REAL,
    threshold_applied REAL,
    selected INTEGER
);
CREATE TABLE human_reviews (
    review_id TEXT PRIMARY KEY,
    classification_id TEXT NOT NULL REFERENCES classifications(classification_id),
    status TEXT CHECK(status IN ('CONFIRMED', 'CORRECTED')),
    reviewer_id TEXT,
    reviewed_at TEXT,
    notes TEXT
);
CREATE TABLE human_review_deltas (
    delta_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL REFERENCES human_reviews(review_id),
    dimension TEXT,
    operation TEXT CHECK(operation IN ('set', 'add', 'remove')),
    original_value TEXT,
    corrected_value TEXT
);
"""


def _uuid() -> str:
    return uuid.uuid4().hex


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


@dataclass(frozen=True)
class StoredEmail:
    email_id: str
    message_id: str
    thread_id: str | None
    sender: str
    recipients: tuple[str, ...]
    subject: str
    body: str
    received_at: datetime | None
    ingested_at: datetime | None
    source: str | None
    raw_ref: str | None


@dataclass(frozen=True)
class StoredLabel:
    dimension: str
    label: str
    score: float | None
    threshold_applied: float | None
    selected: bool


@dataclass(frozen=True)
class StoredClassification:
    classification_id: str
    email_id: str
    status: str
    classifier_version: str
    engine_version: str | None
    question_set_version: str | None
    threshold_set_version: str | None
    raw_scores: dict[str, float]
    engine_request_id: str | None
    confidence: float | None
    band: Band | None
    requires_human_review: bool
    primary_category: PrimaryCategory | None
    secondary_categories: tuple[PrimaryCategory, ...]
    sensitivity: tuple[Sensitivity, ...]
    actions: tuple[Action, ...]
    priority: Priority | None
    received_at: datetime | None
    ingested_at: datetime | None
    scored_at: datetime | None
    classified_at: datetime | None
    source_classification_id: str | None
    queue_reason: str | None
    labels: tuple[StoredLabel, ...]


@dataclass(frozen=True)
class StoredDelta:
    dimension: str
    operation: str
    original_value: str | None
    corrected_value: str | None


@dataclass(frozen=True)
class StoredReview:
    review_id: str
    classification_id: str
    status: str
    reviewer_id: str | None
    reviewed_at: datetime | None
    notes: str | None
    deltas: tuple[StoredDelta, ...]


@dataclass(frozen=True)
class QueueEntry:
    email_id: str
    message_id: str
    subject: str | None
    classification_id: str
    status: str
    band: str | None
    confidence: float | None
    queue_reason: str
    dimensions: dict[str, Any]


_LABEL_DIMENSION_KEYS = {
    "primary_category",
    "secondary_categories",
    "sensitivity",
    "actions",
    "priority",
}


def _project(record: StoredClassification, review: StoredReview) -> StoredClassification:
    """Apply one review's deltas over the automated values (human-review spec:
    'dashboard reads deltas over automated values as current')."""
    primary = record.primary_category
    secondary = list(record.secondary_categories)
    sensitivity = list(record.sensitivity)
    actions = list(record.actions)
    priority = record.priority
    for delta in review.deltas:
        dimension = delta.dimension
        if dimension == "primary_category":
            if delta.corrected_value is not None:
                primary = PrimaryCategory(delta.corrected_value)
        elif dimension == "secondary_categories":
            if delta.operation == "add" and delta.corrected_value is not None:
                secondary.append(PrimaryCategory(delta.corrected_value))
            elif delta.operation == "remove" and delta.original_value is not None:
                secondary = [c for c in secondary if c.value != delta.original_value]
            elif delta.operation == "set":
                secondary = [
                    PrimaryCategory(v) for v in (delta.corrected_value or "").split(",") if v
                ]
        elif dimension == "sensitivity":
            if delta.operation == "add" and delta.corrected_value is not None:
                sensitivity.append(Sensitivity(delta.corrected_value))
            elif delta.operation == "remove" and delta.original_value is not None:
                sensitivity = [s for s in sensitivity if s.value != delta.original_value]
            elif delta.operation == "set":
                sensitivity = [
                    Sensitivity(v) for v in (delta.corrected_value or "").split(",") if v
                ]
        elif dimension == "actions":
            if delta.operation == "add" and delta.corrected_value is not None:
                actions.append(Action(delta.corrected_value))
            elif delta.operation == "remove" and delta.original_value is not None:
                actions = [a for a in actions if a.value != delta.original_value]
            elif delta.operation == "set":
                actions = [Action(v) for v in (delta.corrected_value or "").split(",") if v]
        elif dimension == "priority":
            if delta.corrected_value is not None:
                priority = Priority(delta.corrected_value)
    return dataclasses.replace(
        record,
        primary_category=primary,
        secondary_categories=tuple(secondary),
        sensitivity=tuple(sensitivity),
        actions=tuple(actions),
        priority=priority,
    )


def _json_list(value: str | None) -> list[str]:
    return [] if not value else list(json.loads(value))


class SqliteRepository:
    """Append-only classification repository + review queue read model."""

    def __init__(self, path: str | Any) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_DDL)
        self._conn.commit()

    # --- ingestion ---------------------------------------------------------

    def append_email(
        self,
        email: EmailMessage,
        source: str,
        ingested_at: datetime | None = None,
    ) -> str:
        ingested = ingested_at if ingested_at is not None else datetime.now()
        existing = self._conn.execute(
            "SELECT email_id FROM emails WHERE message_id = ?", (email.message_id,)
        ).fetchone()
        if existing is not None:
            return existing["email_id"]
        email_id = _uuid()
        self._conn.execute(
            "INSERT INTO emails (email_id, message_id, thread_id, sender, recipients,"
            " subject, body, received_at, ingested_at, source, raw_ref)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_id,
                email.message_id,
                email.thread_id,
                email.sender,
                json.dumps(list(email.recipients)),
                email.subject,
                email.body,
                _iso(email.received_at),
                _iso(ingested),
                source,
                None,
            ),
        )
        for attachment in email.attachments:
            self._conn.execute(
                "INSERT INTO email_attachments (attachment_id, email_id, filename,"
                " mime, extracted_text, extraction_status) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _uuid(),
                    email_id,
                    attachment.filename,
                    attachment.mime,
                    attachment.extracted_text,
                    attachment.status.value,
                ),
            )
        self._conn.commit()
        return email_id

    # --- classification appends --------------------------------------------

    def append_classified(
        self,
        email_id: str,
        decision: Decision,
        thresholds: ThresholdConfig | None = None,
        engine_request_id: str | None = None,
        scored_at: datetime | None = None,
        classified_at: datetime | None = None,
    ) -> str:
        return self._append_classification(
            email_id, decision, thresholds, engine_request_id, scored_at, classified_at
        )

    def append_failed(
        self,
        email_id: str,
        decision: Decision,
        thresholds: ThresholdConfig | None = None,
        engine_request_id: str | None = None,
        scored_at: datetime | None = None,
        classified_at: datetime | None = None,
    ) -> str:
        return self._append_classification(
            email_id, decision, thresholds, engine_request_id, scored_at, classified_at
        )

    def _append_classification(
        self,
        email_id: str,
        decision: Decision,
        thresholds: ThresholdConfig | None,
        engine_request_id: str | None,
        scored_at: datetime | None,
        classified_at: datetime | None,
    ) -> str:
        # Idempotent writes (classification-storage): the same email with the
        # same scoring outcome (classifier_version + status + raw_scores) is a
        # duplicate run; a different outcome (relabel/replay) still appends.
        existing = self._conn.execute(
            "SELECT classification_id FROM classifications WHERE email_id = ?"
            " AND classifier_version = ? AND status = ? AND raw_scores = ?"
            " AND engine_request_id IS ?",
            (
                email_id,
                decision.classifier_version,
                decision.status,
                json.dumps(decision.raw_scores),
                engine_request_id,
            ),
        ).fetchone()
        if existing is not None:
            return existing["classification_id"]

        classified = classified_at if classified_at is not None else datetime.now()
        scored = scored_at if scored_at is not None else classified
        email_row = self._conn.execute(
            "SELECT received_at, ingested_at FROM emails WHERE email_id = ?",
            (email_id,),
        ).fetchone()

        classification_id = _uuid()
        self._conn.execute(
            "INSERT INTO classifications (classification_id, email_id, status,"
            " classifier_version, engine_version, question_set_version,"
            " threshold_set_version, raw_scores, engine_request_id, confidence,"
            " classification_band, requires_human_review, primary_category,"
            " secondary_categories, sensitivity, actions, priority, received_at,"
            " ingested_at, scored_at, classified_at, source_classification_id,"
            " queue_reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                classification_id,
                email_id,
                decision.status,
                decision.classifier_version,
                decision.engine_version,
                decision.question_set_version,
                decision.threshold_set_version,
                json.dumps(decision.raw_scores),
                engine_request_id,
                decision.confidence,
                decision.band.value if decision.band is not None else None,
                1 if decision.requires_human_review else 0,
                decision.primary_category.value if decision.primary_category is not None else None,
                json.dumps([c.value for c in decision.secondary_categories]),
                json.dumps([s.value for s in decision.sensitivity]),
                json.dumps([a.value for a in decision.actions]),
                decision.priority.value if decision.priority is not None else None,
                email_row["received_at"],
                email_row["ingested_at"],
                _iso(scored),
                _iso(classified),
                None,
                decision.queue_reason,
            ),
        )
        self._store_labels(classification_id, decision, thresholds)
        self._conn.commit()
        return classification_id

    def _store_labels(
        self,
        classification_id: str,
        decision: Decision,
        thresholds: ThresholdConfig | None,
    ) -> None:
        rows: list[tuple[str, str, str, str, float, float | None, int]] = []
        for key, score in decision.raw_scores.items():
            dimension, _, label = key.partition("/")
            threshold = None
            if thresholds is not None:
                elevated = thresholds.elevated.get(key)
                if elevated is not None:
                    threshold = elevated.auto_threshold
                else:
                    threshold = thresholds.default_auto_threshold
            rows.append((_uuid(), classification_id, dimension, label, score, threshold, 0))
        selected: set[tuple[str, str]] = set()
        if decision.primary_category is not None:
            selected.add(("primary_category", decision.primary_category.value))
        selected.update(("secondary_categories", c.value) for c in decision.secondary_categories)
        selected.update(("sensitivity", s.value) for s in decision.sensitivity)
        selected.update(("actions", a.value) for a in decision.actions)
        if decision.priority is not None:
            selected.add(("priority", decision.priority.value))
        rows = [
            (
                label_id,
                cid,
                dimension,
                label,
                score,
                threshold,
                1 if (dimension, label) in selected else 0,
            )
            for label_id, cid, dimension, label, score, threshold, _flag in rows
        ]
        self._conn.executemany(
            "INSERT INTO classification_labels (label_id, classification_id,"
            " dimension, label, score, threshold_applied, selected)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    # --- reads (classification-storage: latest-record read model) ----------

    def get_email(self, email_id: str) -> StoredEmail:
        row = self._conn.execute("SELECT * FROM emails WHERE email_id = ?", (email_id,)).fetchone()
        return StoredEmail(
            email_id=row["email_id"],
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            sender=row["sender"],
            recipients=tuple(json.loads(row["recipients"])),
            subject=row["subject"],
            body=row["body"],
            received_at=_from_iso(row["received_at"]),
            ingested_at=_from_iso(row["ingested_at"]),
            source=row["source"],
            raw_ref=row["raw_ref"],
        )

    def _classification(self, row: sqlite3.Row) -> StoredClassification:
        classification_id = row["classification_id"]
        labels = tuple(
            StoredLabel(
                dimension=lr["dimension"],
                label=lr["label"],
                score=lr["score"],
                threshold_applied=lr["threshold_applied"],
                selected=bool(lr["selected"]),
            )
            for lr in self._conn.execute(
                "SELECT * FROM classification_labels WHERE classification_id = ?",
                (classification_id,),
            )
        )
        return StoredClassification(
            classification_id=classification_id,
            email_id=row["email_id"],
            status=row["status"],
            classifier_version=row["classifier_version"],
            engine_version=row["engine_version"],
            question_set_version=row["question_set_version"],
            threshold_set_version=row["threshold_set_version"],
            raw_scores=json.loads(row["raw_scores"]),
            engine_request_id=row["engine_request_id"],
            confidence=row["confidence"],
            band=Band(row["classification_band"])
            if row["classification_band"] is not None
            else None,
            requires_human_review=bool(row["requires_human_review"]),
            primary_category=PrimaryCategory(row["primary_category"])
            if row["primary_category"] is not None
            else None,
            secondary_categories=tuple(
                PrimaryCategory(v) for v in _json_list(row["secondary_categories"])
            ),
            sensitivity=tuple(Sensitivity(v) for v in _json_list(row["sensitivity"])),
            actions=tuple(Action(v) for v in _json_list(row["actions"])),
            priority=Priority(row["priority"]) if row["priority"] is not None else None,
            received_at=_from_iso(row["received_at"]),
            ingested_at=_from_iso(row["ingested_at"]),
            scored_at=_from_iso(row["scored_at"]),
            classified_at=_from_iso(row["classified_at"]),
            source_classification_id=row["source_classification_id"],
            queue_reason=row["queue_reason"],
            labels=labels,
        )

    def get_classification(self, classification_id: str) -> StoredClassification:
        row = self._conn.execute(
            "SELECT * FROM classifications WHERE classification_id = ?",
            (classification_id,),
        ).fetchone()
        return self._classification(row)

    def get_classification_history(self, email_id: str) -> list[StoredClassification]:
        rows = self._conn.execute(
            "SELECT * FROM classifications WHERE email_id = ? ORDER BY rowid",
            (email_id,),
        ).fetchall()
        return [self._classification(row) for row in rows]

    def get_current_classification(self, email_id: str) -> StoredClassification:
        """Latest-record read model with the review projection applied: current
        values = the latest review's deltas over the automated values. The
        stored record itself is never mutated (append-only + review history)."""
        row = self._conn.execute(
            "SELECT * FROM classifications WHERE email_id = ? ORDER BY rowid DESC LIMIT 1",
            (email_id,),
        ).fetchone()
        record = self._classification(row)
        reviews = self.list_reviews(email_id)
        if not reviews:
            return record
        return _project(record, reviews[-1])

    def counts(self) -> dict[str, int]:
        return {
            table: self._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 — fixed table names
            ).fetchone()["n"]
            for table in (
                "emails",
                "email_attachments",
                "classifications",
                "classification_labels",
                "human_reviews",
                "human_review_deltas",
            )
        }

    # --- human review (human-review spec) ----------------------------------

    def append_review(
        self,
        classification_id: str,
        status: str,
        reviewer_id: str,
        deltas: list[dict[str, str | None]],
        notes: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> str:
        reviewed = reviewed_at if reviewed_at is not None else datetime.now()
        review_id = _uuid()
        self._conn.execute(
            "INSERT INTO human_reviews (review_id, classification_id, status,"
            " reviewer_id, reviewed_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, classification_id, status, reviewer_id, _iso(reviewed), notes),
        )
        self._conn.executemany(
            "INSERT INTO human_review_deltas (delta_id, review_id, dimension,"
            " operation, original_value, corrected_value) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    _uuid(),
                    review_id,
                    delta["dimension"],
                    delta["operation"],
                    delta.get("original_value"),
                    delta.get("corrected_value"),
                )
                for delta in deltas
            ],
        )
        self._conn.commit()
        return review_id

    def list_reviews(self, email_id: str) -> list[StoredReview]:
        rows = self._conn.execute(
            "SELECT hr.* FROM human_reviews hr"
            " JOIN classifications c ON c.classification_id = hr.classification_id"
            " WHERE c.email_id = ? ORDER BY hr.rowid",
            (email_id,),
        ).fetchall()
        reviews: list[StoredReview] = []
        for row in rows:
            deltas = tuple(
                StoredDelta(
                    dimension=dr["dimension"],
                    operation=dr["operation"],
                    original_value=dr["original_value"],
                    corrected_value=dr["corrected_value"],
                )
                for dr in self._conn.execute(
                    "SELECT * FROM human_review_deltas WHERE review_id = ? ORDER BY rowid",
                    (row["review_id"],),
                )
            )
            reviews.append(
                StoredReview(
                    review_id=row["review_id"],
                    classification_id=row["classification_id"],
                    status=row["status"],
                    reviewer_id=row["reviewer_id"],
                    reviewed_at=_from_iso(row["reviewed_at"]),
                    notes=row["notes"],
                    deltas=deltas,
                )
            )
        return reviews

    def list_review_queue(self, reason: str | None = None) -> list[QueueEntry]:
        """Latest record per email with requires_human_review = 1, optionally
        filtered by queue reason. A review (CONFIRMED or CORRECTED) closes the
        queue entry for its classification (human-review spec)."""
        rows = self._conn.execute(
            "SELECT c.*, e.message_id, e.subject FROM classifications c"
            " JOIN emails e ON e.email_id = c.email_id"
            " WHERE c.requires_human_review = 1"
            " AND c.rowid = (SELECT MAX(c2.rowid) FROM classifications c2"
            "                WHERE c2.email_id = c.email_id)"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM human_reviews hr"
            "   WHERE hr.classification_id = c.classification_id)"
            " ORDER BY c.rowid",
        ).fetchall()
        entries: list[QueueEntry] = []
        for row in rows:
            if reason is not None and row["queue_reason"] != reason:
                continue
            current = self._classification(row)
            entries.append(
                QueueEntry(
                    email_id=row["email_id"],
                    message_id=row["message_id"],
                    subject=row["subject"],
                    classification_id=current.classification_id,
                    status=current.status,
                    band=current.band.value if current.band is not None else None,
                    confidence=current.confidence,
                    queue_reason=row["queue_reason"] or "",
                    dimensions={
                        "primary_category": current.primary_category.value
                        if current.primary_category is not None
                        else None,
                        "secondary_categories": [c.value for c in current.secondary_categories],
                        "sensitivity": [s.value for s in current.sensitivity],
                        "actions": [a.value for a in current.actions],
                        "priority": current.priority.value
                        if current.priority is not None
                        else None,
                    },
                )
            )
        return entries
