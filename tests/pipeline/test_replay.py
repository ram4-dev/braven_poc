"""Work unit 12 — replay under new thresholds (RED tests).

Acceptance scenarios from the classification-storage delta spec:
- Replay relabels from stored scores (T2 records carry unchanged raw scores,
  zero engine requests).
- Replay preserves history (T2 current, T1 retrievable, same raw scores).
- Idempotent writes (re-running replay with the SAME threshold set does not
  append duplicate records).
- Replay goes through the same pure rules ``decide()`` path as the pipeline.
"""

from dataclasses import replace
from pathlib import Path

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import ThresholdConfig
from email_classifier.pipeline.pipeline import Pipeline

FIXTURE = Path("tests/fixtures/inbox_small.json")

T1 = ThresholdConfig.mvp()
# New threshold-set version: same table shape, new version string.
T2 = replace(T1, version="th-t2")
# A threshold variant that actually changes rule outcomes (stricter bars), used
# to prove replay recomputes labels through the pure decide() path.
T2_STRICT = replace(T1, default_auto_threshold=0.99, default_review_floor=0.99, version="th-t99")


class CountingScorer:
    """Spy engine: counts scoring requests, delegates to an inner engine."""

    def __init__(self, inner):
        self.inner = inner
        self.requests = 0

    def score(self, email, questions):
        self.requests += 1
        return self.inner.score(email, questions)


def make_questions():
    from email_classifier.config.loader import load_questions

    return load_questions("src/email_classifier/config/questions.yaml")


def seed(repo, engine=None):
    """Run the pipeline once under T1; return (report, spy-engine)."""
    pipeline = Pipeline(
        source=InboxDatasetSource.from_file(FIXTURE),
        engine=engine or FakeDeterministicScorer(),
        repository=repo,
        thresholds=T1,
        questions=make_questions(),
    )
    return pipeline.run(), engine


def make_replay(repo, thresholds, email_ids):
    from email_classifier.pipeline.replay import replay

    return replay(repository=repo, thresholds=thresholds, email_ids=email_ids)


class TestReplayRelabelsFromStoredScores:
    def test_new_records_carry_t2_with_unchanged_raw_scores(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        make_replay(repo, T2, report.email_ids)

        for email_id in report.email_ids:
            current = repo.get_current_classification(email_id)
            assert current.threshold_set_version == "th-t2"
            # Raw scores copied verbatim from the T1 record.
            t1 = [
                r
                for r in repo.get_classification_history(email_id)
                if r.threshold_set_version == "th-mvp"
            ][0]
            assert current.raw_scores == t1.raw_scores
            assert current.raw_scores.keys() == t1.raw_scores.keys()

    def test_engine_version_and_question_set_version_unchanged(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        make_replay(repo, T2, report.email_ids)

        for email_id in report.email_ids:
            current = repo.get_current_classification(email_id)
            t1 = [
                r
                for r in repo.get_classification_history(email_id)
                if r.threshold_set_version == "th-mvp"
            ][0]
            assert current.engine_version == t1.engine_version
            assert current.question_set_version == t1.question_set_version

    def test_zero_engine_requests_during_replay(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        spy = CountingScorer(FakeDeterministicScorer())
        report, _ = seed(repo, spy)
        assert spy.requests == 4  # one per email, from the pipeline run only

        make_replay(repo, T2, report.email_ids)
        assert spy.requests == 4  # replay issued ZERO engine requests

    def test_relabeling_appends_new_records(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        before = repo.counts()["classifications"]
        make_replay(repo, T2, report.email_ids)
        assert repo.counts()["classifications"] == before + len(report.email_ids)


class TestReplayPreservesHistory:
    def test_t2_current_t1_retrievable_same_raw_scores(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        make_replay(repo, T2, report.email_ids)

        for email_id in report.email_ids:
            current = repo.get_current_classification(email_id)
            assert current.threshold_set_version == "th-t2"

            history = repo.get_classification_history(email_id)
            t1_records = [r for r in history if r.threshold_set_version == "th-mvp"]
            assert len(t1_records) == 1  # T1 record remains retrievable
            assert len(history) == 2  # append-only: T1 + T2, nothing replaced
            assert current.raw_scores == t1_records[0].raw_scores


class TestReplayIdempotentRerun:
    def test_same_threshold_set_does_not_duplicate(self, tmp_path):
        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        make_replay(repo, T2, report.email_ids)
        counts_after_first = repo.counts()["classifications"]
        history_lens = {
            email_id: len(repo.get_classification_history(email_id))
            for email_id in report.email_ids
        }

        second = make_replay(repo, T2, report.email_ids)
        assert repo.counts()["classifications"] == counts_after_first
        for email_id in report.email_ids:
            assert len(repo.get_classification_history(email_id)) == history_lens[email_id]
        assert second.replayed == 0  # everything was already replayed under T2


class TestReplayUsesPureRulesPath:
    def test_labels_recomputed_through_decide(self, tmp_path):
        from email_classifier.domain.rules import decide

        repo = SqliteRepository(tmp_path / "db.sqlite3")
        report, _ = seed(repo)
        make_replay(repo, T2_STRICT, report.email_ids)

        for email_id in report.email_ids:
            current = repo.get_current_classification(email_id)
            t1 = [
                r
                for r in repo.get_classification_history(email_id)
                if r.threshold_set_version == "th-mvp"
            ][0]
            expected = decide(
                t1.raw_scores,
                T2_STRICT,
                engine_version=t1.engine_version,
                question_set_version=t1.question_set_version,
            )
            # Exactly the same pure rules path, fed stored scores + T2.
            assert current.band == expected.band
            assert current.primary_category == expected.primary_category
            assert current.requires_human_review == expected.requires_human_review
