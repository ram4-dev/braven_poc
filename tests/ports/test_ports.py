"""Port Protocol contracts (work unit 2 — RED tests)."""

from datetime import UTC, datetime

import pytest

from email_classifier.domain.models import (
    Action,
    Band,
    Decision,
    EmailMessage,
    PrimaryCategory,
    Priority,
    Question,
    QuestionSet,
    ScoreError,
    ScoreResult,
    Sensitivity,
)
from email_classifier.ports import (
    AttachmentExtractor,
    ClassificationRepository,
    EmailSource,
    ScoringEngine,
)


def _email(message_id: str = "em-0001") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="cliente@ejemplo.com",
        recipients=["seguros@braven.com"],
        subject="Consulta",
        body="Cuerpo del mensaje",
        received_at=datetime(2026, 10, 5, tzinfo=UTC),
        thread_id=None,
        attachments=[],
    )


def _questions() -> QuestionSet:
    return QuestionSet(
        version="qs-v1",
        questions=[
            Question(
                question_id="primary_category/CLAIM_NEW",
                type="noul",
                instructions="i",
                criteria_true="t",
                criteria_false="f",
            )
        ],
    )


def _decision() -> Decision:
    return Decision(
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
        secondary_categories=[],
        sensitivity=[Sensitivity.INTERNAL],
        actions=[Action.NO_ACTION],
        priority=Priority.NORMAL,
        queue_reason=None,
    )


class FakeInboxSource:
    """Structural fake: satisfies EmailSource without any I/O."""

    def list_emails(self) -> list[EmailMessage]:
        return [_email()]


class FakeScoringEngine:
    """Structural fake: satisfies ScoringEngine without any I/O."""

    def score(self, email: EmailMessage, questions: QuestionSet) -> ScoreResult:
        return ScoreResult(
            scores={q.question_id: 0.5 for q in questions.questions},
            engine_version="fake-1",
            question_set_version=questions.version,
        )


class FakeClassificationRepository:
    """Structural fake: satisfies ClassificationRepository without any I/O."""

    def append_email(self, email: EmailMessage, source: str) -> str:
        return "email-1"

    def append_classified(self, email_id: str, decision: Decision) -> str:
        return "classification-1"

    def append_failed(self, email_id: str, decision: Decision) -> str:
        return "classification-failed-1"


class FakeAttachmentExtractor:
    """Structural fake: satisfies AttachmentExtractor without any I/O."""

    def extract(self, email: EmailMessage) -> EmailMessage:
        return email


class TestScoringErrorPort:
    def test_port_error_exists_and_is_exception(self):
        assert issubclass(ScoreError, Exception)
        with pytest.raises(ScoreError):
            raise ScoreError("fail-closed")


class TestEmailSource:
    def test_fake_satisfies_protocol(self):
        source: EmailSource = FakeInboxSource()
        assert isinstance(source, EmailSource)
        emails = source.list_emails()
        assert len(emails) == 1
        assert isinstance(emails[0], EmailMessage)


class TestScoringEngine:
    def test_fake_satisfies_protocol(self):
        engine: ScoringEngine = FakeScoringEngine()
        assert isinstance(engine, ScoringEngine)
        result = engine.score(_email(), _questions())
        assert isinstance(result, ScoreResult)
        assert result.scores["primary_category/CLAIM_NEW"] == 0.5

    def test_runtime_checkable_rejects_non_conforming_class(self):
        class NotAnEngine:
            pass

        assert not isinstance(NotAnEngine(), ScoringEngine)


class TestClassificationRepository:
    def test_fake_satisfies_protocol(self):
        repo: ClassificationRepository = FakeClassificationRepository()
        assert isinstance(repo, ClassificationRepository)
        email_id = repo.append_email(_email(), source="dataset")
        classification_id = repo.append_classified(email_id, _decision())
        assert classification_id == "classification-1"


class TestAttachmentExtractor:
    def test_fake_satisfies_protocol(self):
        extractor: AttachmentExtractor = FakeAttachmentExtractor()
        assert isinstance(extractor, AttachmentExtractor)
        assert extractor.extract(_email()) is not None
