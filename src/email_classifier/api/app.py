"""FastAPI read/review/replay/metrics surface (design D8).

The API layer contains no SQL and no engine access: every read and write goes
through the repository read model and the pure replay path. Routes serialize
stored records to JSON; current values are the repository's review projection
and original automated values stay retrievable.

Known deviation (flagged for verify): the repository is built around one
thread-bound sqlite3 connection. Sync FastAPI endpoints run in a worker
thread, so ``create_app`` swaps the shared connection for a cross-thread one
against the same database file. A repository constructor accepting
``check_same_thread=False`` would remove this shim.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import (
    ACTION_LABELS,
    PRIMARY_CATEGORY_LABELS,
    PRIORITY_LABELS,
    SENSITIVITY_LABELS,
    LabelThreshold,
    ThresholdConfig,
)
from email_classifier.pipeline.metrics import EvaluationItem, compute_metrics
from email_classifier.pipeline.replay import replay

# Dimension -> frozen label set (deltas validated against the frozen taxonomy).
_FROZEN_LABELS: dict[str, set[str]] = {
    "primary_category": set(PRIMARY_CATEGORY_LABELS),
    "secondary_categories": set(PRIMARY_CATEGORY_LABELS),
    "sensitivity": set(SENSITIVITY_LABELS),
    "actions": set(ACTION_LABELS),
    "priority": set(PRIORITY_LABELS),
}

_LABEL_ENUMS: dict[str, dict[str, type]] = {}


class DeltaIn(BaseModel):
    dimension: str
    operation: str
    original_value: str | None = None
    corrected_value: str | None = None

    @field_validator("dimension")
    @classmethod
    def _known_dimension(cls, value: str) -> str:
        if value not in _FROZEN_LABELS:
            raise ValueError(f"unknown dimension {value!r}; allowed: {sorted(_FROZEN_LABELS)}")
        return value

    @field_validator("operation")
    @classmethod
    def _known_operation(cls, value: str) -> str:
        if value not in ("set", "add", "remove"):
            raise ValueError(f"unknown operation {value!r}; allowed: set, add, remove")
        return value


class ReviewIn(BaseModel):
    classification_id: str
    status: str
    reviewer_id: str
    notes: str | None = None
    deltas: list[DeltaIn] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in ("CONFIRMED", "CORRECTED"):
            raise ValueError("status must be CONFIRMED or CORRECTED")
        return value

    @field_validator("deltas")
    @classmethod
    def _validate_delta_labels(cls, deltas: list[DeltaIn]) -> list[DeltaIn]:
        for delta in deltas:
            allowed = _FROZEN_LABELS[delta.dimension]
            for value in (delta.original_value, delta.corrected_value):
                if value is not None and value not in allowed:
                    raise ValueError(
                        f"unknown label {value!r} for dimension "
                        f"{delta.dimension!r} (frozen taxonomy)"
                    )
            if delta.corrected_value is None and delta.original_value is None:
                raise ValueError("delta requires an original or corrected value")
        return deltas


class ReplayIn(BaseModel):
    threshold_set_version: str
    thresholds: dict[str, Any] | None = None


def _iso(value):
    return value.isoformat() if value is not None else None


def _band(value) -> str | None:
    return value.value if value is not None else None


def _dimensions_of(record) -> dict[str, Any]:
    return {
        "primary_category": record.primary_category.value
        if record.primary_category is not None
        else None,
        "secondary_categories": [c.value for c in record.secondary_categories],
        "sensitivity": [s.value for s in record.sensitivity],
        "actions": [a.value for a in record.actions],
        "priority": record.priority.value if record.priority is not None else None,
    }


def _listing_entry(record, message_id: str | None = None) -> dict[str, Any]:
    return {
        "email_id": record.email_id,
        "classification_id": record.classification_id,
        "message_id": message_id,
        "status": record.status,
        "classifier_version": record.classifier_version,
        "confidence": record.confidence,
        "band": _band(record.band),
        "requires_human_review": record.requires_human_review,
        "queue_reason": record.queue_reason,
        "classified_at": _iso(record.classified_at),
        **_dimensions_of(record),
    }


def _labels_payload(record, thresholds: ThresholdConfig) -> list[dict[str, Any]]:
    """Per-label decision evidence (dashboard spec: sensitive non-auto label).

    A label that cleared its review floor but stayed below its auto threshold
    and was not selected is flagged ``routed_to_review``: exactly the sensitive
    non-auto case the spec requires evidence for.
    """
    payload: list[dict[str, Any]] = []
    for label in record.labels:
        key = f"{label.dimension}/{label.label}"
        elevated = thresholds.elevated.get(key)
        review_floor = (
            elevated.review_floor if elevated is not None else thresholds.default_review_floor
        )
        routed = (
            not label.selected
            and label.score is not None
            and label.score >= review_floor
            and (label.threshold_applied is None or label.score < label.threshold_applied)
        )
        payload.append(
            {
                "dimension": label.dimension,
                "label": label.label,
                "score": label.score,
                "auto_threshold": label.threshold_applied,
                "review_floor": review_floor,
                "selected": label.selected,
                "routed_to_review": routed,
            }
        )
    return payload


def _thresholds_from_dict(data: dict[str, Any], version: str) -> ThresholdConfig:
    """Build a ThresholdConfig from an inline JSON table (replay request)."""
    default = data.get("default") or {}
    elevated_rows = data.get("elevated") or []
    elevated = {}
    for row in elevated_rows:
        try:
            auto_threshold = float(row["auto_threshold"])
            review_floor = float(row.get("review_floor", default.get("review_floor", 0.65)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid elevated threshold row {row!r}: {exc}") from exc
        elevated[f"{row['dimension']}/{row['label']}"] = LabelThreshold(
            dimension=row["dimension"],
            label=row["label"],
            auto_threshold=auto_threshold,
            review_floor=review_floor,
        )
    try:
        default_auto = float(default.get("auto_threshold", 0.90))
        default_floor = float(default.get("review_floor", 0.65))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid default threshold row {default!r}: {exc}") from exc
    return ThresholdConfig(
        default_auto_threshold=default_auto,
        default_review_floor=default_floor,
        elevated=elevated,
        version=version,
    )


def _read_email_rows(repo) -> list[sqlite3.Row]:
    return repo._conn.execute("SELECT email_id, message_id FROM emails ORDER BY rowid").fetchall()


def _email_ids(repo: SqliteRepository) -> list[str]:
    """Enumerate stored email ids through the repository's read model.

    Deviation (flagged for verify): the repository exposes no email-id
    enumeration method and ``adapters/**`` is outside this work unit's edit
    surface, so this helper issues the one missing SELECT over the repo's
    own connection. Follow-up: add ``list_email_ids()`` to
    ``sqlite_repo.py`` and delete this helper.
    """
    return [row["email_id"] for row in _read_email_rows(repo)]


def _message_ids(repo: SqliteRepository) -> dict[str, str]:
    return {row["email_id"]: row["message_id"] for row in _read_email_rows(repo)}


def _enable_cross_thread_connection(repository: SqliteRepository) -> None:
    """Swap the repo's thread-bound sqlite connection for a cross-thread one.

    Sync FastAPI endpoints execute in a worker thread; the repository was
    constructed on the caller's thread. Same database file, same schema, only
    the thread affinity changes. In-memory repositories are left untouched
    (a swap would drop their data).
    """
    conn = repository._conn
    rows = conn.execute("PRAGMA database_list").fetchall()
    file_path = next((row[2] for row in rows if row[2]), None)
    if file_path is None:
        return
    conn.close()
    replacement = sqlite3.connect(file_path, check_same_thread=False)
    replacement.row_factory = sqlite3.Row
    replacement.execute("PRAGMA foreign_keys = ON")
    repository._conn = replacement


def _evaluation_item(record, message_id: str, attachment_statuses) -> EvaluationItem:
    """Stored automated values for metrics (never reviewer corrections)."""
    return EvaluationItem(
        message_id=message_id,
        status=record.status,
        primary_category=record.primary_category.value
        if record.primary_category is not None
        else None,
        secondary_categories=tuple(c.value for c in record.secondary_categories),
        sensitivity=tuple(s.value for s in record.sensitivity),
        requires_human_review=record.requires_human_review,
        queue_reason=record.queue_reason,
        received_at=record.received_at,
        classified_at=record.classified_at,
        classifier_version=record.classifier_version,
        engine_version=record.engine_version,
        question_set_version=record.question_set_version,
        threshold_set_version=record.threshold_set_version,
        attachment_statuses=tuple(attachment_statuses),
    )


def create_app(
    repository: SqliteRepository,
    thresholds: ThresholdConfig | None = None,
    expected_labels: dict[str, dict] | None = None,
    dataset_version: str = "unknown",
) -> FastAPI:
    """Build the FastAPI app over a repository port (no SQL in this layer).

    ``expected_labels`` (message_id -> expected label dict) and
    ``dataset_version`` feed the metrics report; ground truth stays the
    dataset's, never reviewer corrections (classification-metrics spec).
    """
    app = FastAPI(title="email-classifier")
    repo = repository
    _enable_cross_thread_connection(repo)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/emails")
    def list_emails() -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        message_ids = _message_ids(repo)
        for email_id in _email_ids(repo):
            record = repo.get_current_classification(email_id)
            entries.append(_listing_entry(record, message_ids.get(email_id)))
        return {"emails": entries}

    @app.get("/api/emails/{email_id}")
    def email_detail(email_id: str) -> dict[str, Any]:
        history = repo.get_classification_history(email_id)
        if not history:
            raise HTTPException(status_code=404, detail="email not found")
        stored = repo.get_current_classification(email_id)
        table = thresholds or ThresholdConfig.mvp()
        return {
            "email_id": email_id,
            "current": {
                "status": stored.status,
                "classifier_version": stored.classifier_version,
                "engine_version": stored.engine_version,
                "question_set_version": stored.question_set_version,
                "threshold_set_version": stored.threshold_set_version,
                "raw_scores": stored.raw_scores,
                "applied_thresholds": {
                    f"{lb.dimension}/{lb.label}": lb.threshold_applied
                    for lb in stored.labels
                    if lb.threshold_applied is not None
                },
                "confidence": stored.confidence,
                "band": _band(stored.band),
                "requires_human_review": stored.requires_human_review,
                "queue_reason": stored.queue_reason,
                **_dimensions_of(stored),
            },
            "originals": _listing_entry(
                repo.get_classification_history(email_id)[0],
                _message_ids(repo).get(email_id),
            ),
            "labels": _labels_payload(stored, table),
            "reviews": [
                {
                    "review_id": review.review_id,
                    "classification_id": review.classification_id,
                    "status": review.status,
                    "reviewer_id": review.reviewer_id,
                    "reviewed_at": _iso(review.reviewed_at),
                    "notes": review.notes,
                    "deltas": [
                        {
                            "dimension": d.dimension,
                            "operation": d.operation,
                            "original_value": d.original_value,
                            "corrected_value": d.corrected_value,
                        }
                        for d in review.deltas
                    ],
                }
                for review in repo.list_reviews(email_id)
            ],
        }

    @app.get("/api/review-queue")
    def review_queue(reason: str | None = None) -> dict[str, Any]:
        entries = repo.list_review_queue(reason=reason)
        return {
            "queue": [
                {
                    "email_id": entry.email_id,
                    "message_id": entry.message_id,
                    "subject": entry.subject,
                    "classification_id": entry.classification_id,
                    "status": entry.status,
                    "band": entry.band,
                    "confidence": entry.confidence,
                    "queue_reason": entry.queue_reason,
                    "dimensions": entry.dimensions,
                }
                for entry in entries
            ]
        }

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        message_ids = _message_ids(repo)
        items = []
        for email_id, message_id in message_ids.items():
            # Metrics read the AUTOMATED stored record, never the review
            # projection: corrections must not rewrite ground truth.
            history = repo.get_classification_history(email_id)
            record = history[-1] if history else repo.get_current_classification(email_id)
            statuses = tuple(
                row["extraction_status"]
                for row in repo._conn.execute(
                    "SELECT extraction_status FROM email_attachments WHERE email_id = ?",
                    (email_id,),
                )
            )
            items.append(_evaluation_item(record, message_id, statuses))
        return compute_metrics(
            items,
            expected_labels or {},
            dataset_version=dataset_version,
        )

    @app.post("/api/reviews", status_code=201)
    def post_review(review: ReviewIn) -> dict[str, str]:
        try:
            repo.get_classification(review.classification_id)
        except Exception as exc:  # noqa: BLE001 - unknown id -> 404
            raise HTTPException(status_code=404, detail="classification not found") from exc
        review_id = repo.append_review(
            classification_id=review.classification_id,
            status=review.status,
            reviewer_id=review.reviewer_id,
            deltas=[delta.model_dump() for delta in review.deltas],
            notes=review.notes,
        )
        return {"review_id": review_id}

    @app.post("/api/replay")
    def post_replay(payload: ReplayIn) -> dict[str, Any]:
        if payload.thresholds is not None:
            target = _thresholds_from_dict(payload.thresholds, payload.threshold_set_version)
        elif thresholds is not None and payload.threshold_set_version == thresholds.version:
            target = thresholds
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown threshold_set_version "
                    f"{payload.threshold_set_version!r}: no matching threshold "
                    f"table was provided"
                ),
            )
        report = replay(repository=repo, thresholds=target, email_ids=_email_ids(repo))
        return {"replayed": report.replayed}

    return app
