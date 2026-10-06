"""Work unit 8 — append-only SQLite classification storage (classification-storage spec RED).

Real tmp_path SQLite file; no mocks. These tests are the acceptance criteria for
the classification-storage spec scenarios listed in task 6.5.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta

import pytest

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
from email_classifier.domain.rules import decide


def make_email(message_id: str = "em-0001") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="broker@example.com",
        recipients=["claims@insurer.com"],
        subject="Denuncia de siniestro",
        body="Adjunto la documentación del siniestro poliza 12345.",
        received_at=datetime(2026, 10, 5, 10, 0, 0),
        attachments=(),
    )


def make_decision(
    engine_request_id: str | None = "req-1",
    status: str = "CLASSIFIED",
    classifier_version: str = "tax-mvp1+qs-v1+eng-jev-1.13+th-35d4c41e",
    raw_scores: dict[str, float] | None = None,
    confidence: float | None = 0.93,
    band: Band | None = Band.AUTOMATIC,
    requires_human_review: bool = False,
    primary: PrimaryCategory | None = PrimaryCategory.CLAIM_NEW,
    queue_reason: str | None = None,
) -> Decision:
    return Decision(
        status=status,
        classifier_version=classifier_version,
        engine_version="jev-1.13",
        question_set_version="qs-v1",
        threshold_set_version="35d4c41e",
        raw_scores=raw_scores if raw_scores is not None else {},
        confidence=confidence,
        band=band,
        requires_human_review=requires_human_review,
        primary_category=primary,
        secondary_categories=(PrimaryCategory.CLAIM_DOCUMENTATION,),
        sensitivity=(Sensitivity.PERSONAL_DATA,),
        actions=(Action.REPLY_REQUIRED,),
        priority=Priority.HIGH,
        queue_reason=queue_reason,
    )


@pytest.fixture()
def repo(tmp_path):
    from email_classifier.adapters.sqlite_repo import SqliteRepository

    return SqliteRepository(tmp_path / "pipeline.sqlite3")


class TestSchemaIsAppendOnly:
    def test_all_six_tables_exist(self, repo, tmp_path):
        conn = sqlite3.connect(tmp_path / "pipeline.sqlite3")
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "emails",
            "email_attachments",
            "classifications",
            "classification_labels",
            "human_reviews",
            "human_review_deltas",
        } <= names

    def test_message_id_unique_constraint_at_schema_level(self, repo, tmp_path):
        """The UNIQUE constraint exists in the DDL (design: message_id UNIQUE).
        Repo-level append_email is idempotent (returns the existing id); the raw
        constraint is what makes duplicates impossible from any writer."""
        email = make_email()
        repo.append_email(email, source="dataset")
        conn = sqlite3.connect(tmp_path / "pipeline.sqlite3")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO emails (email_id, message_id) VALUES ('other', ?)",
                (email.message_id,),
            )

    def test_classifications_status_is_constrained(self, repo, tmp_path):
        email_id = repo.append_email(make_email(), source="dataset")
        conn = sqlite3.connect(tmp_path / "pipeline.sqlite3")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO classifications (classification_id, email_id, status,"
                " classifier_version) VALUES ('c-x', ?, 'MUTATED', 'v1')",
                (email_id,),
            )

    def test_attachment_extraction_status_is_constrained(self, repo, tmp_path):
        email_id = repo.append_email(make_email(), source="dataset")
        conn = sqlite3.connect(tmp_path / "pipeline.sqlite3")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO email_attachments (attachment_id, email_id, filename,"
                " mime, extracted_text, extraction_status) VALUES"
                " ('a-x', ?, 'f.pdf', 'application/pdf', NULL, 'magically_extracted')",
                (email_id,),
            )

    def test_raw_scores_column_rejects_null(self, repo, tmp_path):
        email_id = repo.append_email(make_email(), source="dataset")
        conn = sqlite3.connect(tmp_path / "pipeline.sqlite3")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO classifications (classification_id, email_id, status,"
                " classifier_version, raw_scores) VALUES ('c-y', ?, 'CLASSIFIED', 'v1',"
                " NULL)",
                (email_id,),
            )


class TestEmailPersistence:
    def test_email_row_round_trips(self, repo):
        email = make_email()
        email_id = repo.append_email(email, source="dataset")
        record = repo.get_email(email_id)
        assert record.message_id == "em-0001"
        assert record.sender == "broker@example.com"
        assert record.recipients == ("claims@insurer.com",)
        assert record.source == "dataset"
        assert record.received_at == datetime(2026, 10, 5, 10, 0, 0)
        assert record.ingested_at is not None

    def test_repeated_ingest_returns_existing_email_id(self, repo):
        email = make_email()
        first = repo.append_email(email, source="dataset")
        second = repo.append_email(email, source="dataset")
        assert first == second


class TestCompositeClassifierVersion:
    def test_composite_version_stored_verbatim(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        thresholds = dataclasses.replace(ThresholdConfig.mvp(), version="35d4c41e")
        decision = decide(
            {"primary_category/CLAIM_NEW": 0.93},
            thresholds,
        )
        classification_id = repo.append_classified(email_id, decision)
        record = repo.get_classification(classification_id)
        assert record.classifier_version == "tax-mvp1+qs-v1+eng-jev-1.13+th-35d4c41e"
        assert record.threshold_set_version == "35d4c41e"

    def test_differing_versions_distinguishable_from_records_alone(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        first = repo.append_classified(
            email_id, make_decision(classifier_version="tax-mvp1+qs-v1+eng-jev-1.13+th-aaaa1111")
        )
        second = repo.append_classified(
            email_id, make_decision(classifier_version="tax-mvp1+qs-v1+eng-jev-1.13+th-bbbb2222")
        )
        r1 = repo.get_classification(first)
        r2 = repo.get_classification(second)
        assert r1.classifier_version != r2.classifier_version


class TestVerbatimRawScores:
    def test_labels_are_never_stored_alone(self, repo):
        raw = {f"primary_category/{c.name}": 0.01 for c in PrimaryCategory}
        raw["primary_category/CLAIM_NEW"] = 0.93
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(email_id, make_decision(raw_scores=raw))
        record = repo.get_classification(classification_id)
        assert record.raw_scores == raw
        assert record.raw_scores.keys() == raw.keys()

    def test_full_returned_precision(self, repo):
        raw = {"primary_category/CLAIM_NEW": 0.1234567891234567}
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(
            email_id, make_decision(raw_scores=raw, confidence=0.1234567891234567)
        )
        record = repo.get_classification(classification_id)
        assert record.raw_scores["primary_category/CLAIM_NEW"] == 0.1234567891234567
        assert record.confidence == 0.1234567891234567

    def test_engine_request_id_retained(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(
            email_id, make_decision(), engine_request_id="req-1"
        )
        record = repo.get_classification(classification_id)
        assert record.engine_request_id == "req-1"


class TestPerLabelDecisionRecords:
    def test_auditing_a_rejected_label(self, repo):
        raw = {
            "primary_category/CLAIM_NEW": 0.93,
            "sensitivity/HIGHLY_CONFIDENTIAL": 0.50,  # below its 0.95 elevated auto bar
        }
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(
            email_id,
            make_decision(raw_scores=raw),
            thresholds=ThresholdConfig.mvp(),
        )
        record = repo.get_classification(classification_id)
        rejected = [
            lb
            for lb in record.labels
            if lb.dimension == "sensitivity" and lb.label == "HIGHLY_CONFIDENTIAL"
        ]
        assert len(rejected) == 1
        assert rejected[0].score == 0.50
        assert rejected[0].threshold_applied == 0.95
        assert rejected[0].selected is False
        # the threshold-set version in force is visible on the record
        assert record.threshold_set_version == "35d4c41e"

    def test_selected_label_records_score_threshold_and_selection(self, repo):
        raw = {"primary_category/CLAIM_NEW": 0.93}
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(
            email_id, make_decision(raw_scores=raw), thresholds=ThresholdConfig.mvp()
        )
        record = repo.get_classification(classification_id)
        selected = [lb for lb in record.labels if lb.selected]
        assert len(selected) == 1
        assert selected[0].dimension == "primary_category"
        assert selected[0].label == "CLAIM_NEW"
        assert selected[0].score == 0.93
        assert selected[0].threshold_applied == 0.90


class TestRelabelingAppends:
    def test_reclassification_appends_and_preserves_previous(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        first_id = repo.append_classified(email_id, make_decision(), engine_request_id="req-1")
        second_id = repo.append_classified(
            email_id,
            make_decision(
                classifier_version="tax-mvp1+qs-v1+eng-jev-1.13+th-bbbb2222",
                primary=PrimaryCategory.COMPLAINT,
            ),
            engine_request_id="req-2",
        )
        assert first_id != second_id
        first = repo.get_classification(first_id)
        second = repo.get_classification(second_id)
        assert first.primary_category is PrimaryCategory.CLAIM_NEW
        assert second.primary_category is PrimaryCategory.COMPLAINT
        history = repo.get_classification_history(email_id)
        assert [c.classification_id for c in history] == [first_id, second_id]


class TestLatencyTimestampChain:
    def test_latency_computable_from_storage(self, repo):
        email = make_email()
        email_id = repo.append_email(
            email, source="dataset", ingested_at=datetime(2026, 10, 5, 10, 0, 5)
        )
        scored_at = datetime(2026, 10, 5, 10, 0, 9)
        classified_at = datetime(2026, 10, 5, 10, 0, 10)
        classification_id = repo.append_classified(
            email_id,
            make_decision(),
            scored_at=scored_at,
            classified_at=classified_at,
        )
        record = repo.get_classification(classification_id)
        assert record.received_at == datetime(2026, 10, 5, 10, 0, 0)
        assert record.ingested_at == datetime(2026, 10, 5, 10, 0, 5)
        assert record.scored_at == scored_at
        assert record.classified_at == classified_at
        total = record.classified_at - record.received_at
        per_stage = record.scored_at - record.ingested_at
        assert total == timedelta(seconds=10)
        assert per_stage.total_seconds() > 0

    def test_failed_scoring_still_timestamped(self, repo):
        email = make_email()
        email_id = repo.append_email(email, source="dataset")
        failed = make_decision(
            status="FAILED",
            confidence=None,
            band=None,
            primary=None,
            requires_human_review=True,
            queue_reason="scoring_failed",
        )
        classification_id = repo.append_failed(email_id, failed)
        record = repo.get_classification(classification_id)
        assert record.status == "FAILED"
        assert record.received_at == datetime(2026, 10, 5, 10, 0, 0)
        assert record.ingested_at is not None
        assert record.primary_category is None
        assert record.band is None


class TestLatestRecordReadModel:
    def test_three_records_latest_is_current_and_history_intact(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        ids = [
            repo.append_classified(email_id, make_decision(), engine_request_id=f"req-{n}")
            for n in (1, 2, 3)
        ]
        current = repo.get_current_classification(email_id)
        assert current.classification_id == ids[-1]
        history = repo.get_classification_history(email_id)
        assert [c.classification_id for c in history] == ids

    def test_current_view_returns_latest_labels(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        repo.append_classified(email_id, make_decision(), engine_request_id="req-1")
        last_id = repo.append_classified(
            email_id,
            make_decision(primary=PrimaryCategory.OTHER),
            engine_request_id="req-2",
        )
        current = repo.get_current_classification(email_id)
        assert current.classification_id == last_id
        assert current.primary_category is PrimaryCategory.OTHER


class TestIdempotentWrites:
    def test_repeated_run_reports_already_processed(self, repo):
        email = make_email()
        email_id = repo.append_email(email, source="dataset")
        decision = make_decision(raw_scores={"primary_category/CLAIM_NEW": 0.93})
        first = repo.append_classified(email_id, decision)
        second = repo.append_classified(email_id, decision)
        assert first == second
        counts = repo.counts()
        assert counts["emails"] == 1
        assert counts["classifications"] == 1

    def test_repeated_whole_run_is_idempotent(self, repo):
        decision = make_decision(raw_scores={"primary_category/CLAIM_NEW": 0.93})
        for _ in range(2):  # identical run repeated
            email_id = repo.append_email(make_email(), source="dataset")
            repo.append_classified(email_id, decision)
        counts = repo.counts()
        assert counts["emails"] == 1
        assert counts["classifications"] == 1


class TestReviewDoesNotMutateOriginal:
    def test_correction_lives_in_review_history_only(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        classification_id = repo.append_classified(email_id, make_decision())
        before = repo.get_classification(classification_id)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-7",
            deltas=[
                {
                    "dimension": "primary_category",
                    "operation": "set",
                    "original_value": "CLAIM_NEW",
                    "corrected_value": "CLAIM_UPDATE",
                }
            ],
        )
        after = repo.get_classification(classification_id)
        assert after == before
        reviews = repo.list_reviews(email_id)
        assert len(reviews) == 1
        assert reviews[0].status == "CORRECTED"
        assert reviews[0].deltas[0].corrected_value == "CLAIM_UPDATE"
