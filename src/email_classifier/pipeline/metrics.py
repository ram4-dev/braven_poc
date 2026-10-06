"""Classification metrics over stored classifications + dataset ground truth.

Pure computation (no I/O): the caller feeds ``EvaluationItem`` values (one per
processed email, built from the stored read model), the dataset's frozen
``expected`` label map (the sole truth source — reviewer corrections never
rewrite it), and version strings. The result is a JSON-serializable dict.

Report shape (classification-metrics spec):
- accuracy: numerator/denominator/share — failed emails count as incorrect and
  are never dropped from the denominator.
- per_category: precision/recall for all 16 MVP primary categories; a category
  with no predicted or no expected instances is reported as absent (``None``
  plus ``*_absent: true``), not as zero.
- sensitive_classes: the five sensitive classes reported separately with a
  false-negative rate. A false negative whose email DID reach human review
  (e.g. the floor..auto tier gap) is not a silent miss; the FN rate reflects
  only emails that produced no review entry at all.
- review_rate: queued/processed with raw counts, failed emails included.
- latency: per-email seconds, run aggregate, failed subset when available.
- other_rate: OTHER share + the share of OTHER emails that cleared no category
  floor at all (``no_category_cleared_floor`` queue reason).
- versions: dataset/question-set/threshold-set/engine/composite versions.
- limitations: non-text attachments excluded from scoring, with the affected
  attachment count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from email_classifier.domain.models import PRIMARY_CATEGORY_LABELS

SENSITIVE_CLASSES: tuple[str, ...] = (
    "FRAUD_SUSPICION",
    "LEGAL",
    "PERSONAL_DATA",
    "SENSITIVE_PERSONAL_DATA",
    "HIGHLY_CONFIDENTIAL",
)

# The OTHER sub-population that cleared no category floor at all.
_NO_FLOOR_REASON = "no_category_cleared_floor"

_LIMITATION_STATEMENT = (
    "Images and other non-text-extractable attachments were excluded from "
    "scoring; OCR coverage is outside this measurement."
)


@dataclass(frozen=True)
class EvaluationItem:
    """One processed email as seen by metrics (from the stored read model).

    ``primary_category``/``secondary_categories``/``sensitivity`` carry the
    stored AUTOMATED values, never reviewer corrections: the dataset's
    expected labels stay the sole ground truth (D7).
    """

    message_id: str
    status: str  # "CLASSIFIED" | "FAILED"
    primary_category: str | None
    secondary_categories: tuple[str, ...] = ()
    sensitivity: tuple[str, ...] = ()
    requires_human_review: bool = False
    queue_reason: str | None = None
    received_at: datetime | None = None
    classified_at: datetime | None = None
    classifier_version: str | None = None
    engine_version: str | None = None
    question_set_version: str | None = None
    threshold_set_version: str | None = None
    attachment_statuses: tuple[str, ...] = field(default_factory=tuple)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _precision_recall(expected_ids: set[str], predicted_ids: set[str]) -> dict:
    true_positive = len(expected_ids & predicted_ids)
    precision = true_positive / len(predicted_ids) if predicted_ids else None
    recall = true_positive / len(expected_ids) if expected_ids else None
    return {
        "true_positive_count": true_positive,
        "expected_count": len(expected_ids),
        "predicted_count": len(predicted_ids),
        "precision": precision,
        "precision_absent": precision is None,
        "recall": recall,
        "recall_absent": recall is None,
    }


def compute_metrics(
    items: list[EvaluationItem],
    expected: dict[str, dict],
    *,
    dataset_version: str,
) -> dict:
    """Compute the classification-metrics report (pure; JSON-serializable)."""
    processed = len(items)
    classified_items = [i for i in items if i.status == "CLASSIFIED"]
    failed_items = [i for i in items if i.status != "CLASSIFIED"]

    # --- accuracy: failed emails are incorrect, never dropped  --------------
    correct = sum(
        1
        for i in classified_items
        if i.primary_category is not None
        and i.primary_category == expected.get(i.message_id, {}).get("primary_category")
    )
    accuracy = {
        "numerator": correct,
        "denominator": processed,
        "share": _ratio(correct, processed),
    }

    # --- per-category precision/recall over all 16 MVP primary categories ---
    per_category: dict[str, dict] = {}
    for label in PRIMARY_CATEGORY_LABELS:
        expected_ids = {
            i.message_id
            for i in items
            if expected.get(i.message_id, {}).get("primary_category") == label
        }
        predicted_ids = {i.message_id for i in classified_items if i.primary_category == label}
        per_category[label] = _precision_recall(expected_ids, predicted_ids)

    # --- sensitive classes: separate P/R + false-negative rate --------------
    sensitive: dict[str, dict] = {}
    for label in SENSITIVE_CLASSES:
        expected_ids = {
            i.message_id
            for i in items
            if label in expected.get(i.message_id, {}).get("sensitivity", [])
        }
        predicted_ids = {i.message_id for i in classified_items if label in i.sensitivity}
        entry = _precision_recall(expected_ids, predicted_ids)
        # A false negative = expected but not predicted. Silent miss = the
        # email produced no review entry at all; an email routed to review
        # (e.g. sensitive signal between floor and auto threshold) is a
        # human-reviewed case, not a silent miss.
        fn_ids = expected_ids - predicted_ids
        silent = {
            i.message_id for i in items if i.message_id in fn_ids and not i.requires_human_review
        }
        entry["false_negative_count"] = len(fn_ids)
        entry["silent_miss_count"] = len(silent)
        entry["false_negative_rate"] = len(silent) / len(expected_ids) if expected_ids else None
        sensitive[label] = entry

    # --- review rate (raw counts; failed emails included) -------------------
    queued = sum(1 for i in items if i.requires_human_review)
    review_rate = {
        "queued": queued,
        "processed": processed,
        "rate": _ratio(queued, processed),
    }

    # --- latency (stored timestamp chain; failed subset separate) -----------
    def _latency_for(item: EvaluationItem) -> float | None:
        if item.received_at is None or item.classified_at is None:
            return None
        start, end = item.received_at, item.classified_at
        # Stored chains may mix aware (fixture Z timestamps) and naive
        # (datetime.now()) values; compare on a common naive timeline.
        if (start.tzinfo is None) != (end.tzinfo is None):
            if start.tzinfo is not None:
                start = start.replace(tzinfo=None)
            if end.tzinfo is not None:
                end = end.replace(tzinfo=None)
        return (end - start).total_seconds()

    per_email = [{"message_id": i.message_id, "seconds": _latency_for(i)} for i in items]

    def _aggregate(latencies: list[float]) -> dict:
        return {
            "count": len(latencies),
            "mean_seconds": sum(latencies) / len(latencies) if latencies else None,
        }

    measured = [s for s in map(_latency_for, items) if s is not None]
    failed_measured = [s for s in map(_latency_for, failed_items) if s is not None]
    latency = {
        "per_email": per_email,
        "aggregate": _aggregate(measured),
        "failed_subset": _aggregate(failed_measured),
    }

    # --- OTHER rate ----------------------------------------------------------
    other_items = [i for i in classified_items if i.primary_category == "OTHER"]
    no_floor = [i for i in other_items if i.queue_reason == _NO_FLOOR_REASON]
    other_rate = {
        "other_count": len(other_items),
        "processed": processed,
        "share": _ratio(len(other_items), processed),
        "no_category_floor_cleared_count": len(no_floor),
        "no_category_floor_cleared_share": _ratio(len(no_floor), len(other_items)),
    }

    # --- version attribution --------------------------------------------------
    versions = {
        "dataset_version": dataset_version,
        "question_set_version": _single(items, "question_set_version"),
        "threshold_set_version": _single(items, "threshold_set_version"),
        "engine_version": _single(items, "engine_version"),
        "classifier_version": _single(items, "classifier_version"),
    }

    # --- known limitations: attachment gap ------------------------------------
    non_text = sum(1 for i in items for status in i.attachment_statuses if status != "extracted")
    limitations = {
        "non_text_attachments_excluded": True,
        "statement": _LIMITATION_STATEMENT,
        "affected_attachment_count": non_text,
    }

    return {
        "accuracy": accuracy,
        "per_category": per_category,
        "sensitive_classes": sensitive,
        "review_rate": review_rate,
        "latency": latency,
        "other_rate": other_rate,
        "versions": versions,
        "limitations": limitations,
    }


def _single(items: list[EvaluationItem], attribute: str) -> str | None:
    values = {getattr(i, attribute) for i in items}
    values.discard(None)
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values))
    return "mixed"
