"""Pipeline orchestration: ingest -> score -> rules -> append (design data flow).

The pipeline is engine- and source-agnostic: it only touches the
``EmailSource``, ``ScoringEngine`` and ``ClassificationRepository`` ports —
never httpx, zen_jev or any concrete adapter (jev-scoring §A anti-corruption
boundary). Rules stay in the pure domain core; the pipeline only wires stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from email_classifier.domain.models import (
    Decision,
    EmailMessage,
    QuestionSet,
    ScoreError,
    ThresholdConfig,
)
from email_classifier.domain.rules import decide

_STATUS_CLASSIFIED = "CLASSIFIED"
_STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class RunReport:
    """Run counts: everything processed is accounted for (zero silent drops)."""

    ingested: int
    processed: int
    classified: int
    failed: int
    queued: int
    email_ids: tuple[str, ...]


class Pipeline:
    """One ingest-to-label run over a source, an engine and a repository."""

    def __init__(
        self,
        *,
        source,
        engine,
        repository,
        thresholds: ThresholdConfig,
        questions: QuestionSet,
        now: datetime | None = None,
    ) -> None:
        self._source = source
        self._engine = engine
        self._repository = repository
        self._thresholds = thresholds
        self._questions = questions
        self._now = now

    def run(self) -> RunReport:
        emails = self._source.list_emails()
        email_ids: list[str] = []
        classified = 0
        failed = 0
        queued = 0

        for email in emails:
            email_id = self._repository.append_email(
                email, source="inbox_dataset", ingested_at=self._now
            )
            email_ids.append(email_id)

            # Exactly one scoring request per email: all questions travel
            # together in a single score() call (jev-scoring spec).
            try:
                result = self._engine.score(email, self._questions)
            except ScoreError:
                decision = self._failed_decision()
                self._repository.append_failed(email_id, decision)
                failed += 1
                queued += 1  # failed scoring is queued (review_routing: failed)
                continue

            decision = decide(
                result.scores,
                self._thresholds,
                engine_version=result.engine_version,
                question_set_version=result.question_set_version,
            )
            self._repository.append_classified(
                email_id,
                decision,
                thresholds=self._thresholds,
                engine_request_id=result.engine_request_id,
            )
            classified += 1
            if decision.requires_human_review:
                queued += 1

        processed = classified + failed
        return RunReport(
            ingested=len(emails),
            processed=processed,
            classified=classified,
            failed=failed,
            queued=queued,
            email_ids=tuple(email_ids),
        )

    def _failed_decision(self) -> Decision:
        """Fail-closed decision: no fabricated label, band or confidence."""
        return decide(
            {},
            self._thresholds,
            engine_version="unknown",
            question_set_version=self._questions.version,
            error=ScoreError("scoring failed"),
        )


__all__ = ["Pipeline", "RunReport", "EmailMessage"]
