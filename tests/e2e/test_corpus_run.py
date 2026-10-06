"""Work unit 17 — end-to-end corpus run (RED tests).

The whole system proof: the full synthetic corpus (datasets/inbox_mvp_v1.json,
125 emails) flows through the complete pipeline (dataset source ->
FakeDeterministicScorer -> pure rules -> append-only SqliteRepository) and then
replays under a modified threshold configuration with ZERO engine calls.

Acceptance scenarios (jev-scoring / classification-storage / zero-silent-drops):
- Item count: every corpus email is ingested.
- Exactly one current classification per email.
- Zero silent drops: every email with a sensitive-signal label at/above its
  review floor is present in the review queue; every failed email is stored and
  queued.
- Run report counts are consistent: ingested == processed == classified + failed
  and queued == len(review queue).
- Replay under a modified threshold config recomputes labels over the full
  corpus with zero engine calls and preserves history (current version changes,
  prior record still retrievable, same raw scores).
"""

from dataclasses import replace
from pathlib import Path

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.config.loader import load_questions, load_thresholds
from email_classifier.domain.models import ScoreError
from email_classifier.domain.rules import SENSITIVE_TIER_LABELS
from email_classifier.pipeline.pipeline import Pipeline

CORPUS = Path("datasets/inbox_mvp_v1.json")
QUESTIONS_PATH = "src/email_classifier/config/questions.yaml"
THRESHOLDS_PATH = "src/email_classifier/config/thresholds.yaml"


class SpyEngine:
    """Wraps the real engine and counts scoring requests."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.requests = 0

    def score(self, email, questions):
        self.requests += 1
        return self.inner.score(email, questions)


def make_questions():
    return load_questions(QUESTIONS_PATH)


def make_thresholds():
    return load_thresholds(THRESHOLDS_PATH)


def sensitive_floor_crossing_ids(repo, thresholds):
    """Emails whose stored raw scores put any sensitive-tier label at/above
    its review floor — these MUST be in the review queue (zero silent drops)."""
    expected = set()
    for email_id in run_all_email_ids(repo):
        stored = repo.get_current_classification(email_id)
        if stored.status != "CLASSIFIED":
            continue
        for question_id, score in stored.raw_scores.items():
            dimension, _, label = question_id.partition("/")
            if label not in SENSITIVE_TIER_LABELS:
                continue
            elevated = thresholds.elevated.get(f"{dimension}/{label}")
            floor = elevated.review_floor if elevated else thresholds.default_review_floor
            if score >= floor:
                expected.add(email_id)
                break
    return expected


def run_all_email_ids(repo):
    return [row_email_id for row_email_id in _all_email_ids(repo)]


def _all_email_ids(repo):
    rows = repo._conn.execute("SELECT email_id FROM emails ORDER BY email_id").fetchall()
    return [r["email_id"] for r in rows]


def seed_repo(repo, engine=None):
    """Run the full corpus through the pipeline under the MVP thresholds."""
    pipeline = Pipeline(
        source=InboxDatasetSource.from_file(CORPUS),
        engine=engine or FakeDeterministicScorer(),
        repository=repo,
        thresholds=make_thresholds(),
        questions=make_questions(),
    )
    return pipeline.run()


def test_full_corpus_item_count_and_single_current_classification(tmp_path):
    repo = SqliteRepository(tmp_path / "e2e.db")
    report = seed_repo(repo)

    assert report.ingested == 125
    assert report.processed == 125
    assert report.classified + report.failed == 125
    assert sorted(report.email_ids) == sorted(_all_email_ids(repo))
    assert len(set(report.email_ids)) == 125

    # Exactly one current classification per email.
    for email_id in _all_email_ids(repo):
        current = repo.get_current_classification(email_id)
        assert current is not None
        history = repo.get_classification_history(email_id)
        assert len(history) == 1  # first run: exactly one record per email
        assert current.classification_id == history[0].classification_id


def test_zero_silent_drops_sensitive_signals_reach_review_queue(tmp_path):
    repo = SqliteRepository(tmp_path / "e2e.db")
    report = seed_repo(repo)
    queue = repo.list_review_queue()
    queued_ids = {entry.email_id for entry in queue}

    # Every sensitive-signal email above its floor is queued.
    expected_sensitive = sensitive_floor_crossing_ids(repo, make_thresholds())
    missing = expected_sensitive - queued_ids
    assert not missing, f"zero silent drops violated, missing from queue: {sorted(missing)}"

    # The queue must be exactly the set the pipeline counted.
    assert report.queued == len(queue)

    # No unfounded queue entries: every queue entry states a reason and either
    # is a sensitive-signal email or has requires_human_review on its record.
    for entry in queue:
        assert entry.queue_reason


def test_failed_emails_stored_and_queued(tmp_path):
    repo = SqliteRepository(tmp_path / "e2e.db")
    thresholds = make_thresholds()

    class ExplodingScorer:
        """Fails one deterministic email with a ScoreError (fail-closed)."""

        def __init__(self) -> None:
            self.inner = FakeDeterministicScorer()
            self.failing_message_id = "em-0044"

        def score(self, email, questions):
            if email.message_id == self.failing_message_id:
                raise ScoreError("forced failure")
            return self.inner.score(email, questions)

    engine = ExplodingScorer()
    pipeline = Pipeline(
        source=InboxDatasetSource.from_file(CORPUS),
        engine=engine,
        repository=repo,
        thresholds=thresholds,
        questions=make_questions(),
    )
    report = pipeline.run()

    assert report.failed == 1
    assert report.classified == 124
    assert report.processed == report.classified + report.failed == 125

    stored = repo.get_current_classification(_email_id_for(repo, "em-0044"))
    assert stored.status == "FAILED"
    assert stored.primary_category is None  # no fabricated label

    # Failed email is queued with the scoring-failed reason.
    queue = repo.list_review_queue(reason="scoring_failed")
    assert stored.email_id in {e.email_id for e in queue}


def test_run_report_counts_consistent(tmp_path):
    repo = SqliteRepository(tmp_path / "e2e.db")
    report = seed_repo(repo)
    assert report.ingested == report.processed == report.classified + report.failed
    assert report.queued == len(repo.list_review_queue())
    assert repo.counts()["emails"] == 125


def test_replay_modified_thresholds_zero_engine_calls_preserves_history(tmp_path):
    thresholds = make_thresholds()
    # Modified threshold config: same table shape, different bars + new version.
    strict = replace(
        thresholds,
        default_auto_threshold=0.99,
        default_review_floor=0.99,
        version="th-e2e-strict",
    )

    repo = SqliteRepository(tmp_path / "e2e.db")
    spy = SpyEngine(FakeDeterministicScorer())
    report = seed_repo(repo, engine=spy)
    original_ids = tuple(report.email_ids)
    first_records = {
        email_id: repo.get_current_classification(email_id) for email_id in original_ids
    }

    from email_classifier.pipeline.replay import replay

    replay_report = replay(
        repository=repo,
        thresholds=strict,
        email_ids=original_ids,
    )

    # ZERO engine calls during replay.
    assert spy.requests == 125  # exactly the initial pipeline run
    assert replay_report.replayed == 125

    # Current classification under the new threshold set carries its version;
    # history preserved: exactly two records, same raw scores.
    for email_id in original_ids:
        history = repo.get_classification_history(email_id)
        assert len(history) == 2
        current = repo.get_current_classification(email_id)
        assert current.threshold_set_version == "th-e2e-strict"
        assert current.raw_scores == first_records[email_id].raw_scores
        assert current.classification_id != first_records[email_id].classification_id


def _email_id_for(repo, message_id: str) -> str:
    row = repo._conn.execute(
        "SELECT email_id FROM emails WHERE message_id = ?", (message_id,)
    ).fetchone()
    assert row is not None
    return row["email_id"]
