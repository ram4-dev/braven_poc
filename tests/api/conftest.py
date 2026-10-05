"""Shared API test seeding: scripted engine + pipeline runs over the fixture.

The API layer never sees an engine; tests seed storage through the real
pipeline (work units 11-12 path) and drive the app via FastAPI TestClient.
"""

from pathlib import Path

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.domain.models import (
    ScoreError,
    ScoreResult,
    ThresholdConfig,
)

FIXTURE = Path("tests/fixtures/inbox_small.json")


def make_questions():
    from email_classifier.config.loader import load_questions

    return load_questions("src/email_classifier/config/questions.yaml")


class ScriptedScorer:
    """Deterministic engine: fixed raw scores per message_id (missing -> 0.0)."""

    engine_version = "scripted-1"

    def __init__(self, scores_by_message_id=None, failing=(), default=None):
        self.scores_by_message_id = scores_by_message_id or {}
        self.failing = set(failing)
        self.default = default or {}
        self.requests = 0

    def score(self, email, questions):
        self.requests += 1
        if email.message_id in self.failing:
            raise ScoreError(f"engine unavailable for {email.message_id}")
        scores = dict(self.default)
        scores.update(self.scores_by_message_id.get(email.message_id, {}))
        for question in questions.questions:
            scores.setdefault(question.question_id, 0.0)
        return ScoreResult(
            scores=scores,
            engine_version=self.engine_version,
            question_set_version=questions.version,
        )


def seed(repo, scorer=None):
    """Run the pipeline once over the fixture; return (report, engine)."""
    from email_classifier.pipeline.pipeline import Pipeline

    engine = scorer or FakeDeterministicScorer()
    pipeline = Pipeline(
        source=InboxDatasetSource.from_file(FIXTURE),
        engine=engine,
        repository=repo,
        thresholds=ThresholdConfig.mvp(),
        questions=make_questions(),
    )
    return pipeline.run(), engine


def fixture_dataset():
    return InboxDatasetSource.from_file(FIXTURE)
