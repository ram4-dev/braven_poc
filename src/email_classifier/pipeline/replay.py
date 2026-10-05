"""Replay: relabel stored emails from their stored raw scores under a new
threshold-set version (classification-storage spec, "Replay under new
thresholds").

Replay issues ZERO engine calls: it recomputes labels by feeding each email's
stored verbatim raw scores back through the same pure rules ``decide()`` path
the pipeline uses, then appends a new classification record carrying the new
threshold-set version alongside the unchanged raw scores and engine version.
Append-only storage + the repository's idempotent dedup key make a re-run with
the same threshold set a no-op (no duplicate records).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from email_classifier.domain.models import Decision, ThresholdConfig


@dataclass(frozen=True)
class ReplayReport:
    """Replay counts: every stored email accounted for."""

    replayed: int
    email_ids: tuple[str, ...]


def replay(
    *,
    repository,
    thresholds: ThresholdConfig,
    email_ids: tuple[str, ...] | list[str],
    now: datetime | None = None,
) -> ReplayReport:
    """Relabel the given stored emails from their latest stored raw scores
    under ``thresholds``. Zero engine requests; same pure rules path as the
    pipeline. The storage port has no email-enumeration method, so the caller
    supplies the ids (e.g. from a prior run report).
    """
    email_ids = tuple(email_ids)
    replayed = 0

    for email_id in email_ids:
        stored = repository.get_current_classification(email_id)
        if stored.status != "CLASSIFIED":
            # Nothing to relabel without stored scores (failed scoring).
            continue

        # Idempotent re-run: an email already labelled under this exact
        # threshold-set version from the same stored scores is a duplicate;
        # report it as already processed instead of appending again.
        already_replayed = any(
            record.threshold_set_version == thresholds.version
            and record.raw_scores == stored.raw_scores
            for record in repository.get_classification_history(email_id)
        )
        if already_replayed:
            continue

        decision: Decision = _decide_from_stored(stored, thresholds)
        repository.append_classified(
            email_id,
            decision,
            thresholds=thresholds,
            engine_request_id=None,
            classified_at=now,
        )
        replayed += 1

    return ReplayReport(replayed=replayed, email_ids=email_ids)


def _decide_from_stored(stored, thresholds: ThresholdConfig) -> Decision:
    """Recompute the decision through the pure rules path (no engine access)."""
    from email_classifier.domain.rules import decide

    return decide(
        dict(stored.raw_scores),
        thresholds,
        engine_version=stored.engine_version or "unknown",
        question_set_version=stored.question_set_version or "unknown",
    )


__all__ = ["ReplayReport", "replay"]
