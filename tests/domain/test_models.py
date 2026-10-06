"""Domain model contracts (work unit 2 — RED tests)."""

import dataclasses
from datetime import UTC, datetime

import pytest

from email_classifier.domain.models import (
    ACTION_LABELS,
    PRIMARY_CATEGORY_LABELS,
    PRIORITY_LABELS,
    SENSITIVITY_LABELS,
    Action,
    Attachment,
    AttachmentStatus,
    Band,
    Decision,
    EmailMessage,
    PrimaryCategory,
    Priority,
    Question,
    QuestionSet,
    ScoreResult,
    Sensitivity,
    ThresholdConfig,
)


class TestBand:
    def test_band_is_exactly_the_three_canonical_values(self):
        assert [b.value for b in Band] == ["AUTOMATIC", "UNCERTAIN", "HUMAN_REVIEW"]

    def test_band_is_not_a_taxonomy_label(self):
        all_labels = PRIMARY_CATEGORY_LABELS + SENSITIVITY_LABELS + ACTION_LABELS + PRIORITY_LABELS
        for band in Band:
            assert band.value not in all_labels


class TestFrozenLabelEnums:
    def test_primary_categories_match_taxonomy_mvp(self):
        assert PRIMARY_CATEGORY_LABELS == [
            "NEW_LEAD",
            "QUOTE_REQUEST",
            "NEW_POLICY",
            "POLICY_RENEWAL",
            "POLICY_CHANGE",
            "POLICY_CANCELLATION",
            "CLAIM_NEW",
            "CLAIM_UPDATE",
            "CLAIM_DOCUMENTATION",
            "PAYMENT_BILLING",
            "COMPLAINT",
            "FRAUD_SUSPICION",
            "LEGAL",
            "REGULATORY",
            "PARTNERSHIP",
            "OTHER",
        ]
        assert len(PrimaryCategory) == 16

    def test_sensitivity_matches_taxonomy_mvp(self):
        assert SENSITIVITY_LABELS == [
            "PUBLIC",
            "INTERNAL",
            "CONFIDENTIAL",
            "HIGHLY_CONFIDENTIAL",
            "PERSONAL_DATA",
            "SENSITIVE_PERSONAL_DATA",
        ]
        assert len(Sensitivity) == 6

    def test_actions_match_taxonomy_mvp(self):
        assert ACTION_LABELS == [
            "NO_ACTION",
            "REPLY_REQUIRED",
            "DOCUMENT_REQUIRED",
            "APPROVAL_REQUIRED",
            "ESCALATE",
            "URGENT",
        ]
        assert len(Action) == 6

    def test_priority_matches_taxonomy_mvp(self):
        assert PRIORITY_LABELS == ["LOW", "NORMAL", "HIGH", "CRITICAL"]
        assert len(Priority) == 4

    def test_deferred_categories_are_not_enumerable(self):
        deferred = [
            "CLAIM_PAYMENT",
            "CLAIM_REJECTION",
            "UNDERWRITING",
            "BROKER_AGENT",
            "REINSURANCE",
            "SUPPLIER",
        ]
        all_values = {m.value for m in PrimaryCategory}
        for label in deferred:
            assert label not in all_values
            with pytest.raises(KeyError):
                PrimaryCategory[label]


class TestEmailMessage:
    def test_complete_email_normalized(self):
        received = datetime(2026, 10, 5, 14, 32, tzinfo=UTC)
        email = EmailMessage(
            message_id="em-0001",
            sender="cliente@ejemplo.com",
            recipients=["seguros@braven.com"],
            subject="Consulta de poliza",
            body="Necesito informacion sobre mi poliza.",
            received_at=received,
            thread_id="th-01",
            attachments=[
                Attachment(
                    filename="denuncia.pdf",
                    mime="application/pdf",
                    extracted_text="Texto del documento",
                    status=AttachmentStatus.EXTRACTED,
                )
            ],
        )
        assert email.subject == "Consulta de poliza"
        assert email.body.startswith("Necesito")
        assert email.sender == "cliente@ejemplo.com"
        assert email.recipients == ["seguros@braven.com"]
        assert email.received_at == received
        assert email.thread_id == "th-01"
        assert email.attachments[0].filename == "denuncia.pdf"
        assert email.attachments[0].extracted_text == "Texto del documento"
        assert email.attachments[0].status is AttachmentStatus.EXTRACTED

    def test_missing_optional_fields_do_not_fail(self):
        email = EmailMessage(
            message_id="em-0002",
            sender="cliente@ejemplo.com",
            recipients=["seguros@braven.com"],
            subject="Sin hilo",
            body="Cuerpo",
            received_at=datetime(2026, 10, 5, tzinfo=UTC),
            thread_id=None,
            attachments=[],
        )
        assert email.thread_id is None
        assert email.attachments == []

    def test_attachment_status_values(self):
        assert [s.value for s in AttachmentStatus] == [
            "extracted",
            "not_text_extractable",
            "failed",
        ]

    def test_email_message_is_immutable(self):
        email = EmailMessage(
            message_id="em-0003",
            sender="a@b.com",
            recipients=["c@d.com"],
            subject="s",
            body="b",
            received_at=datetime(2026, 10, 5, tzinfo=UTC),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            email.subject = "changed"  # type: ignore[misc]


class TestScoreResult:
    def test_holds_one_probability_per_question(self):
        result = ScoreResult(
            scores={"primary_category/CLAIM_NEW": 0.96, "sensitivity/PERSONAL_DATA": 0.81},
            engine_version="jev-1.13",
            question_set_version="qs-v1",
        )
        assert result.scores["primary_category/CLAIM_NEW"] == 0.96
        assert result.engine_version == "jev-1.13"


class TestThresholdConfig:
    def test_mvp_default_and_elevated_tiers(self):
        config = ThresholdConfig.mvp()
        assert config.default_auto_threshold == 0.90
        assert config.default_review_floor == 0.65
        elevated = config.elevated
        assert elevated["primary_category/FRAUD_SUSPICION"].auto_threshold == 0.95
        assert elevated["primary_category/FRAUD_SUSPICION"].review_floor == 0.40
        assert elevated["primary_category/LEGAL"].auto_threshold == 0.95
        assert elevated["sensitivity/HIGHLY_CONFIDENTIAL"].review_floor == 0.40

    def test_is_frozen(self):
        config = ThresholdConfig.mvp()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.default_auto_threshold = 0.5  # type: ignore[misc]


class TestQuestionSet:
    def test_mvp_shape(self):
        question = Question(
            question_id="primary_category/CLAIM_NEW",
            type="noul",
            instructions="Does the email report a new claim?",
            criteria_true="...",
            criteria_false="...",
        )
        qset = QuestionSet(version="qs-v1", questions=[question])
        assert qset.version == "qs-v1"
        assert qset.by_id("primary_category/CLAIM_NEW") is question

    def test_question_is_frozen(self):
        question = Question(
            question_id="primary_category/LEGAL",
            type="noul",
            instructions="i",
            criteria_true="t",
            criteria_false="f",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            question.instructions = "x"  # type: ignore[misc]


class TestDecision:
    def test_decision_shape(self):
        decision = Decision(
            status="CLASSIFIED",
            classifier_version="tax-mvp1+qs-v1+eng-jev-1.13+th-abcd1234",
            engine_version="jev-1.13",
            question_set_version="qs-v1",
            threshold_set_version="th-abcd1234",
            raw_scores={"primary_category/CLAIM_NEW": 0.96},
            confidence=0.96,
            band=Band.AUTOMATIC,
            requires_human_review=False,
            primary_category=PrimaryCategory.CLAIM_NEW,
            secondary_categories=[PrimaryCategory.CLAIM_DOCUMENTATION],
            sensitivity=[Sensitivity.PERSONAL_DATA],
            actions=[Action.REPLY_REQUIRED],
            priority=Priority.HIGH,
            queue_reason=None,
        )
        assert decision.band is Band.AUTOMATIC
        assert decision.primary_category is PrimaryCategory.CLAIM_NEW
        assert decision.requires_human_review is False

    def test_decision_is_frozen(self):
        decision = Decision(
            status="CLASSIFIED",
            classifier_version="v",
            engine_version="e",
            question_set_version="q",
            threshold_set_version="t",
            raw_scores={},
            confidence=0.0,
            band=Band.HUMAN_REVIEW,
            requires_human_review=True,
            primary_category=PrimaryCategory.OTHER,
            secondary_categories=[],
            sensitivity=[],
            actions=[],
            priority=Priority.NORMAL,
            queue_reason=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.band = Band.AUTOMATIC  # type: ignore[misc]

    def test_failed_decision_has_no_labels(self):
        decision = Decision(
            status="FAILED",
            classifier_version="v",
            engine_version="e",
            question_set_version="q",
            threshold_set_version="t",
            raw_scores={},
            confidence=None,
            band=None,
            requires_human_review=True,
            primary_category=None,
            secondary_categories=[],
            sensitivity=[],
            actions=[],
            priority=None,
            queue_reason="scoring_failed",
        )
        assert decision.primary_category is None
        assert decision.confidence is None
        assert decision.queue_reason == "scoring_failed"
