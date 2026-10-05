"""Work unit 11 — pipeline orchestration (RED tests).

Acceptance scenarios from the delta specs: email-ingestion (replaceable source,
empty source), jev-scoring (one scoring call per email, engine replaced without
policy changes, fail closed / no silent drop) and classification-rules (the
same pure rules path for every engine). The pipeline MUST be engine- and
source-agnostic: it only sees the ports, never httpx/zen_jev or the dataset
adapter internals.
"""

from dataclasses import fields
from pathlib import Path

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import (
    Band,
    ScoreError,
    ScoreResult,
    ThresholdConfig,
)

FIXTURE = Path("tests/fixtures/inbox_small.json")


def make_questions():
    from email_classifier.config.loader import load_questions

    return load_questions("src/email_classifier/config/questions.yaml")


class CountingScorer:
    """Spy engine: counts scoring requests, delegates to an inner engine."""

    def __init__(self, inner):
        self.inner = inner
        self.requests = 0

    def score(self, email, questions):
        self.requests += 1
        return self.inner.score(email, questions)


class StubScorer:
    """A DIFFERENT engine behind the same boundary (same port, no shared code)."""

    def score(self, email, questions):
        scores = {q.question_id: 0.5 for q in questions.questions}
        return ScoreResult(
            scores=scores,
            engine_version="stub-1",
            question_set_version=questions.version,
        )


class FlakyScorer:
    """Engine that fails for chosen emails and scores the rest normally."""

    def __init__(self, inner, failing_message_ids):
        self.inner = inner
        self.failing = set(failing_message_ids)

    def score(self, email, questions):
        if email.message_id in self.failing:
            raise ScoreError(f"engine unavailable for {email.message_id}")
        return self.inner.score(email, questions)


class ListSource:
    """Minimal replaceable source: same EmailSource boundary, no dataset code."""

    def __init__(self, emails):
        self.emails = list(emails)

    def list_emails(self):
        return list(self.emails)


def fixture_source():
    return InboxDatasetSource.from_file(FIXTURE)


def make_pipeline(repo, source, engine):
    from email_classifier.pipeline.pipeline import Pipeline

    return Pipeline(
        source=source,
        engine=engine,
        repository=repo,
        thresholds=ThresholdConfig.mvp(),
        questions=make_questions(),
    )


def run(repo, source, engine):
    return make_pipeline(repo, source, engine).run()


class TestOneScoringRequestPerEmail:
    def test_exactly_one_request_per_email(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        spy = CountingScorer(FakeDeterministicScorer())
        report = run(repo, fixture_source(), spy)

        assert report.ingested == 4
        assert spy.requests == 4
        assert report.classified == 4
        assert report.failed == 0

    def test_every_email_has_a_stored_classification(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report = run(repo, fixture_source(), FakeDeterministicScorer())

        for email_id in report.email_ids:
            record = repo.get_current_classification(email_id)
            assert record.status == "CLASSIFIED"
            assert len(record.raw_scores) == 28


class TestEngineSwapWithoutPolicyChanges:
    def test_two_engines_same_decision_shape(self, tmp_path):
        repo_a = SqliteRepository(tmp_path / "a.sqlite3")
        repo_b = SqliteRepository(tmp_path / "b.sqlite3")
        report_a = run(repo_a, fixture_source(), FakeDeterministicScorer())
        report_b = run(repo_b, fixture_source(), StubScorer())

        assert report_a.classified == 4
        assert report_b.classified == 4
        for email_id_a, email_id_b in zip(report_a.email_ids, report_b.email_ids, strict=True):
            dec_a = repo_a.get_current_classification(email_id_a)
            dec_b = repo_b.get_current_classification(email_id_b)
            # Same Decision shape through the same pipeline: identical record
            # structure and status, same threshold/question versions — only
            # the engine version, scores and rule outcomes differ.
            assert isinstance(dec_a, type(dec_b))
            assert tuple(f.name for f in fields(dec_a)) == tuple(
                f.name for f in fields(dec_b)
            )
            assert dec_a.status == dec_b.status == "CLASSIFIED"
            assert dec_a.classifier_version != dec_b.classifier_version
            assert dec_a.question_set_version == dec_b.question_set_version
            assert dec_a.threshold_set_version == dec_b.threshold_set_version
            # Band vocabulary is policy, never engine vocabulary.
            assert dec_a.band in (Band.AUTOMATIC, Band.UNCERTAIN, Band.HUMAN_REVIEW)
            assert dec_b.band in (Band.AUTOMATIC, Band.UNCERTAIN, Band.HUMAN_REVIEW)
            assert len(dec_a.raw_scores) == len(dec_b.raw_scores) == 28
            # Per-label scores remain available for both engines (no aggregate
            # replaces the per-label scores).
            assert all(
                isinstance(v, float) and 0.0 <= v <= 1.0
                for v in dec_a.raw_scores.values()
            )
            assert all(
                isinstance(v, float) and 0.0 <= v <= 1.0
                for v in dec_b.raw_scores.values()
            )


class TestSourceReplacement:
    def test_list_source_produces_same_outcome_as_dataset_source(self, tmp_path):
        dataset_repo = SqliteRepository(tmp_path / "dataset.sqlite3")
        dataset_source = fixture_source()
        report_dataset = run(dataset_repo, dataset_source, FakeDeterministicScorer())

        list_repo = SqliteRepository(tmp_path / "list.sqlite3")
        report_list = run(
            list_repo,
            ListSource(dataset_source.list_emails()),
            FakeDeterministicScorer(),
        )

        assert report_list.ingested == report_dataset.ingested == 4
        for email_id_a, email_id_b in zip(
            report_dataset.email_ids, report_list.email_ids, strict=True
        ):
            dec_a = dataset_repo.get_current_classification(email_id_a)
            dec_b = list_repo.get_current_classification(email_id_b)
            # Deterministic engine => the replaceable source changes nothing
            # downstream: same message, same scores, same decision.
            assert dec_a.raw_scores == dec_b.raw_scores
            assert dec_a.primary_category == dec_b.primary_category
            assert dec_a.band == dec_b.band
            assert dec_a.confidence == dec_b.confidence


class TestNoSilentDrop:
    def test_engine_failure_stored_failed_and_queued(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        source = fixture_source()
        failing_id = source.list_emails()[1].message_id
        spy = CountingScorer(FlakyScorer(FakeDeterministicScorer(), {failing_id}))

        report = run(repo, source, spy)

        # Run counts account for the failure: everything processed is counted.
        assert report.ingested == 4
        assert report.processed == 4
        assert report.classified == 3
        assert report.failed == 1
        # Queued = the failed email plus any classified email routed to review
        # by band/sensitive rules — every queued decision surfaces in storage.
        assert report.queued == len(repo.list_review_queue())
        assert report.queued >= 1

        # The failed email is present in storage, not dropped.
        by_message = {
            repo.get_email(eid).message_id: eid for eid in report.email_ids
        }
        failed_record = repo.get_current_classification(by_message[failing_id])
        assert failed_record.status == "FAILED"
        assert failed_record.primary_category is None
        assert failed_record.confidence is None

        # ...and it is in the review queue with a stated reason. The queue may
        # also contain legitimately queued classified emails (sensitive/uncertain
        # bands) — the failed one must be present with its own reason.
        queue = repo.list_review_queue()
        failed_entry = next(
            (e for e in queue if e.message_id == failing_id), None
        )
        assert failed_entry is not None
        assert failed_entry.queue_reason == "scoring_failed"

    def test_zero_silent_drops_for_sensitive_signals(self, tmp_path):
        """Every queued decision must surface as a review-queue entry."""
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report = run(repo, fixture_source(), FakeDeterministicScorer())

        queued_in_storage = len(repo.list_review_queue())
        assert report.queued == queued_in_storage


class TestEmptyRun:
    def test_empty_source_zero_counts_no_error(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report = run(repo, ListSource([]), FakeDeterministicScorer())

        assert report.ingested == 0
        assert report.processed == 0
        assert report.classified == 0
        assert report.failed == 0
        assert report.queued == 0
        assert report.email_ids == ()
        assert repo.counts()["classifications"] == 0
        assert repo.counts()["emails"] == 0


class TestRepeatedRun:
    def test_repeated_run_does_not_duplicate_records(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        source = fixture_source()
        engine = FakeDeterministicScorer()

        first = run(repo, source, engine)
        second = run(repo, source, engine)

        assert first.classified == second.classified == 4
        assert repo.counts()["emails"] == 4
        assert repo.counts()["classifications"] == 4
        for email_id in second.email_ids:
            assert len(repo.get_classification_history(email_id)) == 1
