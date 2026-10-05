"""Work unit 9 — review persistence + queue read/filter (human-review spec RED).

Real tmp_path SQLite file; no mocks. These tests are the acceptance criteria
for the human-review spec scenarios listed in task 6.7.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from email_classifier.domain.models import (
    Action,
    Band,
    Decision,
    EmailMessage,
    PrimaryCategory,
    Priority,
    Sensitivity,
)


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
    status: str = "CLASSIFIED",
    band: Band | None = Band.UNCERTAIN,
    requires_human_review: bool = True,
    primary: PrimaryCategory | None = PrimaryCategory.CLAIM_UPDATE,
    secondary: tuple[PrimaryCategory, ...] = (PrimaryCategory.CLAIM_DOCUMENTATION,),
    sensitivity: tuple[Sensitivity, ...] = (Sensitivity.PERSONAL_DATA, Sensitivity.INTERNAL),
    actions: tuple[Action, ...] = (Action.REPLY_REQUIRED,),
    priority: Priority | None = Priority.HIGH,
    confidence: float | None = 0.72,
    queue_reason: str | None = "uncertain_band",
) -> Decision:
    return Decision(
        status=status,
        classifier_version="tax-mvp1+qs-v1+eng-jev-1.13+th-35d4c41e",
        engine_version="jev-1.13",
        question_set_version="qs-v1",
        threshold_set_version="35d4c41e",
        raw_scores={},
        confidence=confidence,
        band=band,
        requires_human_review=requires_human_review,
        primary_category=primary,
        secondary_categories=secondary,
        sensitivity=sensitivity,
        actions=actions,
        priority=priority,
        queue_reason=queue_reason,
    )


@pytest.fixture()
def repo(tmp_path):
    from email_classifier.adapters.sqlite_repo import SqliteRepository

    return SqliteRepository(tmp_path / "pipeline.sqlite3")


def queue_email(repo, **decision_kwargs) -> tuple[str, str]:
    email_id = repo.append_email(make_email(), source="dataset")
    classification_id = repo.append_classified(email_id, make_decision(**decision_kwargs))
    return email_id, classification_id


class TestConfirmation:
    def test_confirmed_review_leaves_queue(self, repo):
        email_id, classification_id = queue_email(repo)
        assert len(repo.list_review_queue()) == 1
        review_id = repo.append_review(
            classification_id,
            status="CONFIRMED",
            reviewer_id="reviewer-1",
            deltas=[],
        )
        assert review_id
        assert repo.list_review_queue() == []

    def test_confirmed_status_is_stored(self, repo):
        _email_id, classification_id = queue_email(repo)
        review_id = repo.append_review(
            classification_id, status="CONFIRMED", reviewer_id="reviewer-1", deltas=[]
        )
        reviews = repo.list_reviews(_email_id)
        assert reviews[0].status == "CONFIRMED"
        assert reviews[0].review_id == review_id


class TestSingleDimensionCorrection:
    def test_one_delta_others_recorded_unchanged(self, repo):
        _email_id, classification_id = queue_email(repo)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-2",
            deltas=[
                {
                    "dimension": "primary_category",
                    "operation": "set",
                    "original_value": "CLAIM_UPDATE",
                    "corrected_value": "CLAIM_NEW",
                }
            ],
        )
        # projection: corrected primary over automated values elsewhere
        current = repo.get_current_classification(_email_id)
        assert current.primary_category is PrimaryCategory.CLAIM_NEW
        # unchanged dimensions come from the automated record
        assert current.secondary_categories == (PrimaryCategory.CLAIM_DOCUMENTATION,)
        assert current.sensitivity == (
            Sensitivity.PERSONAL_DATA,
            Sensitivity.INTERNAL,
        )
        assert current.actions == (Action.REPLY_REQUIRED,)
        assert current.priority is Priority.HIGH


class TestMultiDimensionCorrection:
    def test_one_review_one_delta_per_changed_dimension(self, repo):
        _email_id, classification_id = queue_email(repo)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-3",
            deltas=[
                {
                    "dimension": "sensitivity",
                    "operation": "set",
                    "original_value": "PERSONAL_DATA,INTERNAL",
                    "corrected_value": "CONFIDENTIAL",
                },
                {
                    "dimension": "actions",
                    "operation": "set",
                    "original_value": "REPLY_REQUIRED",
                    "corrected_value": "ESCALATE",
                },
                {
                    "dimension": "priority",
                    "operation": "set",
                    "original_value": "HIGH",
                    "corrected_value": "CRITICAL",
                },
            ],
        )
        reviews = repo.list_reviews(_email_id)
        assert len(reviews) == 1
        assert len(reviews[0].deltas) == 3
        current = repo.get_current_classification(_email_id)
        assert current.sensitivity == (Sensitivity.CONFIDENTIAL,)
        assert current.actions == (Action.ESCALATE,)
        assert current.priority is Priority.CRITICAL


class TestMultiLabelOperations:
    def test_add_secondary_label(self, repo):
        _email_id, classification_id = queue_email(repo)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-4",
            deltas=[
                {
                    "dimension": "secondary_categories",
                    "operation": "add",
                    "original_value": None,
                    "corrected_value": "LEGAL",
                }
            ],
        )
        current = repo.get_current_classification(_email_id)
        assert current.secondary_categories == (
            PrimaryCategory.CLAIM_DOCUMENTATION,
            PrimaryCategory.LEGAL,
        )

    def test_remove_sensitivity_label(self, repo):
        _email_id, classification_id = queue_email(repo)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-5",
            deltas=[
                {
                    "dimension": "sensitivity",
                    "operation": "remove",
                    "original_value": "INTERNAL",
                    "corrected_value": None,
                }
            ],
        )
        current = repo.get_current_classification(_email_id)
        assert current.sensitivity == (Sensitivity.PERSONAL_DATA,)


class TestOriginalPreserved:
    def test_original_automated_values_reviewer_timestamp_status_retrievable(self, repo):
        _email_id, classification_id = queue_email(repo)
        repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-6",
            deltas=[
                {
                    "dimension": "primary_category",
                    "operation": "set",
                    "original_value": "CLAIM_UPDATE",
                    "corrected_value": "CLAIM_NEW",
                }
            ],
            reviewed_at=datetime(2026, 10, 5, 12, 30, 0),
        )
        # correction is current...
        current = repo.get_current_classification(_email_id)
        assert current.primary_category is PrimaryCategory.CLAIM_NEW
        # ...but the original automated record is untouched and retrievable
        original = repo.get_classification(classification_id)
        assert original.primary_category is PrimaryCategory.CLAIM_UPDATE
        assert original.classification_id == classification_id
        review = repo.list_reviews(_email_id)[0]
        assert review.reviewer_id == "reviewer-6"
        assert review.reviewed_at == datetime(2026, 10, 5, 12, 30, 0)
        assert review.status == "CORRECTED"
        assert review.deltas[0].original_value == "CLAIM_UPDATE"


class TestReviewHistory:
    def test_history_retained_and_ordered(self, repo):
        _email_id, classification_id = queue_email(repo)
        first = repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-7",
            deltas=[
                {
                    "dimension": "priority",
                    "operation": "set",
                    "original_value": "HIGH",
                    "corrected_value": "CRITICAL",
                }
            ],
            reviewed_at=datetime(2026, 10, 5, 11, 0, 0),
        )
        second = repo.append_review(
            classification_id,
            status="CORRECTED",
            reviewer_id="reviewer-8",
            deltas=[
                {
                    "dimension": "priority",
                    "operation": "set",
                    "original_value": "CRITICAL",
                    "corrected_value": "LOW",
                }
            ],
            reviewed_at=datetime(2026, 10, 5, 12, 0, 0),
        )
        reviews = repo.list_reviews(_email_id)
        assert [r.review_id for r in reviews] == [first, second]
        assert reviews[0].reviewer_id == "reviewer-7"
        assert reviews[1].reviewer_id == "reviewer-8"
        # latest review wins in the projection
        current = repo.get_current_classification(_email_id)
        assert current.priority is Priority.LOW


class TestQueueListing:
    def test_entry_exposes_email_dimensions_band_confidence_reason(self, repo):
        _email_id, _classification_id = queue_email(repo)
        queue = repo.list_review_queue()
        assert len(queue) == 1
        entry = queue[0]
        assert entry.message_id == "em-0001"
        assert entry.band == "UNCERTAIN"
        assert entry.confidence == 0.72
        assert entry.queue_reason == "uncertain_band"
        assert entry.dimensions["primary_category"] == "CLAIM_UPDATE"
        assert entry.dimensions["secondary_categories"] == ["CLAIM_DOCUMENTATION"]
        assert entry.dimensions["sensitivity"] == ["PERSONAL_DATA", "INTERNAL"]
        assert entry.dimensions["actions"] == ["REPLY_REQUIRED"]
        assert entry.dimensions["priority"] == "HIGH"

    def test_automatically_classified_email_is_not_queued(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        repo.append_classified(
            email_id,
            make_decision(
                band=Band.AUTOMATIC,
                requires_human_review=False,
                confidence=0.96,
                queue_reason=None,
                primary=PrimaryCategory.NEW_LEAD,
            ),
        )
        assert repo.list_review_queue() == []

    def test_failed_scoring_is_queued(self, repo):
        email_id = repo.append_email(make_email(), source="dataset")
        repo.append_failed(
            email_id,
            make_decision(
                status="FAILED",
                band=None,
                primary=None,
                confidence=None,
                queue_reason="scoring_failed",
            ),
        )
        queue = repo.list_review_queue()
        assert len(queue) == 1
        assert queue[0].queue_reason == "scoring_failed"


class TestQueueFiltering:
    def test_filter_by_reason_returns_only_matching(self, repo):
        for mid, reason in (("em-1", "uncertain_band"), ("em-2", "scoring_failed")):
            email_id = repo.append_email(make_email(mid), source="dataset")
            repo.append_classified(email_id, make_decision(queue_reason=reason))
        filtered = repo.list_review_queue(reason="scoring_failed")
        assert [e.message_id for e in filtered] == ["em-2"]
        # filtering never changes the total queue size
        assert len(repo.list_review_queue()) == 2
