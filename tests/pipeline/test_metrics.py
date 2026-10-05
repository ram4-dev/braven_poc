"""Work unit 15 — classification metrics (RED tests).

Acceptance scenarios from the classification-metrics delta spec:
- Dataset expected labels are the sole ground truth; corrections never rewrite
  truth (metrics stay comparable after reviews).
- Accuracy with numerator + denominator exposed; failed emails never dropped.
- Per-category precision/recall for every MVP primary category; absent
  instances reported as absent, not zero.
- Sensitive classes (FRAUD_SUSPICION, LEGAL, PERSONAL_DATA,
  SENSITIVE_PERSONAL_DATA, HIGHLY_CONFIDENTIAL) reported separately, with a
  false-negative rate; an email between review floor and auto threshold counts
  as reviewed, not as a silent miss.
- Review rate with raw counts, failed emails included.
- Latency per email + run aggregate + failed subset.
- OTHER rate incl. the share that cleared no category floor.
- Version attribution (dataset/question-set/threshold-set/engine/composite).
- Attachment gap stated (non-text-extractable count).
"""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import ThresholdConfig
from email_classifier.pipeline.metrics import EvaluationItem, compute_metrics
from email_classifier.pipeline.pipeline import Pipeline

FIXTURE = Path("tests/fixtures/inbox_small.json")
BASE = datetime(2026, 10, 6, 12, 0, 0)

SENSITIVE_CLASSES = (
    "FRAUD_SUSPICION",
    "LEGAL",
    "PERSONAL_DATA",
    "SENSITIVE_PERSONAL_DATA",
    "HIGHLY_CONFIDENTIAL",
)


def expected_map():
    source = InboxDatasetSource.from_file(FIXTURE)
    source.list_emails()
    return dict(source._expected)


def item(message_id="em-0001", **overrides):
    defaults = dict(
        message_id=message_id,
        status="CLASSIFIED",
        primary_category="CLAIM_NEW",
        secondary_categories=("CLAIM_DOCUMENTATION",),
        sensitivity=("PERSONAL_DATA",),
        requires_human_review=False,
        queue_reason=None,
        received_at=BASE,
        classified_at=BASE + timedelta(seconds=5),
        classifier_version="cv-1",
        engine_version="eng-1",
        question_set_version="qs-1",
        threshold_set_version="th-1",
        attachment_statuses=("extracted", "not_text_extractable"),
    )
    defaults.update(overrides)
    return EvaluationItem(**defaults)


def seeded_repo(tmp_path):
    repo = SqliteRepository(tmp_path / "db.sqlite3")
    pipeline = Pipeline(
        source=InboxDatasetSource.from_file(FIXTURE),
        engine=FakeDeterministicScorer(),
        repository=repo,
        thresholds=ThresholdConfig.mvp(),
        questions=__import__(
            "email_classifier.config.loader", fromlist=["load_questions"]
        ).load_questions("src/email_classifier/config/questions.yaml"),
    )
    report = pipeline.run()
    return repo, report


class TestGroundTruthIsTheDataset:
    def test_accuracy_uses_expected_labels(self):
        items = [
            item("em-0001", primary_category="CLAIM_NEW"),
            item("em-0002", primary_category="QUOTE_REQUEST"),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="inbox_small_v1")
        # em-0001 matches expected CLAIM_NEW; em-0002 predicted QUOTE_REQUEST
        # vs expected NEW_LEAD is a miss computed against the DATASET label.
        assert report["accuracy"]["numerator"] == 1
        assert report["accuracy"]["denominator"] == 2

    def test_corrections_do_not_rewrite_truth(self, tmp_path):
        repo, _ = seeded_repo(tmp_path)
        source = InboxDatasetSource.from_file(FIXTURE)
        source.list_emails()
        items = [
            item_from_row(row, att)
            for row, att in _stored_rows(repo)
        ]
        before = compute_metrics(items, expected_map(), dataset_version="inbox_small_v1")

        # A reviewer "corrects" one email's primary category: stored records
        # are append-only, and metrics read the stored automated values — the
        # dataset's expected labels stay the truth source.
        email_id = items[0].message_id
        # map message_id -> email_id via repo
        row = repo._conn.execute(
            "SELECT email_id FROM emails WHERE message_id = ?", (email_id,)
        ).fetchone()
        history = repo.get_classification_history(row["email_id"])
        repo.append_review(
            history[-1].classification_id,
            "CORRECTED",
            "reviewer-1",
            [
                {
                    "dimension": "primary_category",
                    "operation": "set",
                    "original_value": "CLAIM_NEW",
                    "corrected_value": "OTHER",
                }
            ],
        )
        items_after = [
            item_from_row(row, att) for row, att in _stored_rows(repo)
        ]
        after = compute_metrics(
            items_after, expected_map(), dataset_version="inbox_small_v1"
        )
        assert after["accuracy"] == before["accuracy"]


def _stored_rows(repo):
    """Latest stored classification per email + attachment statuses."""
    rows = repo._conn.execute(
        "SELECT c.*, e.message_id FROM classifications c"
        " JOIN emails e ON e.email_id = c.email_id"
        " WHERE c.rowid = (SELECT MAX(c2.rowid) FROM classifications c2"
        "                  WHERE c2.email_id = c.email_id) ORDER BY c.rowid"
    ).fetchall()
    attachments = {}
    for att in repo._conn.execute(
        "SELECT email_id, extraction_status FROM email_attachments"
    ):
        attachments.setdefault(att["email_id"], []).append(att["extraction_status"])
    return [(row, tuple(attachments.get(row["email_id"], ()))) for row in rows]


def item_from_row(row, attachment_statuses):
    from datetime import datetime as dt

    def parse(value):
        return None if value is None else dt.fromisoformat(value)

    return EvaluationItem(
        message_id=row["message_id"],
        status=row["status"],
        primary_category=row["primary_category"],
        secondary_categories=tuple(json.loads(row["secondary_categories"] or "[]")),
        sensitivity=tuple(json.loads(row["sensitivity"] or "[]")),
        requires_human_review=bool(row["requires_human_review"]),
        queue_reason=row["queue_reason"],
        received_at=parse(row["received_at"]),
        classified_at=parse(row["classified_at"]),
        classifier_version=row["classifier_version"],
        engine_version=row["engine_version"],
        question_set_version=row["question_set_version"],
        threshold_set_version=row["threshold_set_version"],
        attachment_statuses=attachment_statuses,
    )


class TestAccuracy:
    def test_numerator_and_denominator_exposed(self):
        report = compute_metrics([item()], expected_map(), dataset_version="d")
        assert report["accuracy"]["numerator"] == 1
        assert report["accuracy"]["denominator"] == 1
        assert report["accuracy"]["share"] == 1.0

    def test_failed_emails_counted_incorrect_never_dropped(self):
        items = [
            item("em-0001"),
            item(
                "em-0002",
                status="FAILED",
                primary_category=None,
                secondary_categories=(),
                sensitivity=(),
            ),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        assert report["accuracy"]["denominator"] == 2
        assert report["accuracy"]["numerator"] == 1


class TestPerCategory:
    def test_precision_and_recall_per_category(self):
        items = [
            item("em-0001", primary_category="CLAIM_NEW"),
            item("em-0002", primary_category="PAYMENT_BILLING"),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        claim = report["per_category"]["CLAIM_NEW"]
        assert claim["precision"] == 1.0
        assert claim["recall"] == 1.0
        # NEW_LEAD: expected (em-0002) but predicted PAYMENT_BILLING -> recall 0.
        lead = report["per_category"]["NEW_LEAD"]
        assert lead["expected_count"] == 1
        assert lead["predicted_count"] == 0
        assert lead["precision"] is None
        assert lead["precision_absent"] is True
        assert lead["recall"] == 0.0

    def test_category_with_no_expected_instances_reported_absent(self):
        items = [item("em-0001", primary_category="COMPLAINT")]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        entry = report["per_category"]["PARTNERSHIP"]
        assert entry["expected_count"] == 0
        assert entry["predicted_count"] == 0
        assert entry["recall"] is None
        assert entry["recall_absent"] is True

    def test_all_mvp_primary_categories_reported(self):
        report = compute_metrics([item()], expected_map(), dataset_version="d")
        assert len(report["per_category"]) == 16


class TestSensitiveClassesSeparate:
    def test_each_sensitive_class_has_its_own_metrics(self):
        report = compute_metrics([item()], expected_map(), dataset_version="d")
        for label in SENSITIVE_CLASSES:
            assert label in report["sensitive_classes"]
            entry = report["sensitive_classes"][label]
            assert "precision" in entry and "recall" in entry
        # PERSONAL_DATA (expected + predicted on em-0001) is not merged with
        # the other sensitive classes: its recall is 1.0 while e.g.
        # HIGHLY_CONFIDENTIAL has no expected instances here.
        assert report["sensitive_classes"]["PERSONAL_DATA"]["recall"] == 1.0


class TestFalseNegatives:
    def test_missing_sensitive_label_counts_as_false_negative(self):
        items = [
            item(
                "em-0004",
                primary_category="OTHER",
                secondary_categories=(),
                sensitivity=(),
                requires_human_review=False,
                queue_reason=None,
            )
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        entry = report["sensitive_classes"]["SENSITIVE_PERSONAL_DATA"]
        # em-0004 expected does not carry SENSITIVE_PERSONAL_DATA; use an item
        # whose expected carries it instead: craft expected directly.
        report2 = compute_metrics(
            items,
            {
                "em-0004": {
                    "primary_category": "LEGAL",
                    "secondary_categories": [],
                    "sensitivity": ["SENSITIVE_PERSONAL_DATA"],
                }
            },
            dataset_version="d",
        )
        entry2 = report2["sensitive_classes"]["SENSITIVE_PERSONAL_DATA"]
        assert entry2["false_negative_count"] == 1
        assert entry2["silent_miss_count"] == 1
        assert entry2["false_negative_rate"] == 1.0
        # The unrelated default expected map has no such instance: absent.
        assert entry["expected_count"] == 0

    def test_auto_tier_gap_counts_as_reviewed_not_silent_miss(self):
        # Expected SENSITIVE_PERSONAL_DATA; stored output lacks it, but the
        # email was routed to human review (floor..auto gap) -> not a silent
        # miss; the FN rate only reflects emails with no review entry at all.
        items = [
            item(
                "em-0004",
                primary_category="LEGAL",
                sensitivity=(),
                requires_human_review=True,
                queue_reason="sensitive_signal",
            )
        ]
        expected = {
            "em-0004": {
                "primary_category": "LEGAL",
                "secondary_categories": [],
                "sensitivity": ["SENSITIVE_PERSONAL_DATA"],
            }
        }
        report = compute_metrics(items, expected, dataset_version="d")
        entry = report["sensitive_classes"]["SENSITIVE_PERSONAL_DATA"]
        assert entry["false_negative_count"] == 1
        assert entry["silent_miss_count"] == 0
        assert entry["false_negative_rate"] == 0.0


class TestReviewRate:
    def test_review_rate_with_raw_counts(self):
        items = [
            item("em-0001"),
            item("em-0002", primary_category="NEW_LEAD"),
            item(
                "em-0003",
                primary_category="PAYMENT_BILLING",
                requires_human_review=True,
                queue_reason="uncertain_band",
            ),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        assert report["review_rate"]["queued"] == 1
        assert report["review_rate"]["processed"] == 3
        assert report["review_rate"]["rate"] == pytest.approx(1 / 3)

    def test_failed_emails_included_in_review_rate(self):
        items = [
            item(
                "em-0001",
                status="FAILED",
                primary_category=None,
                secondary_categories=(),
                sensitivity=(),
                requires_human_review=True,
                queue_reason="scoring_failed",
            )
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        assert report["review_rate"]["queued"] == 1
        assert report["review_rate"]["processed"] == 1


class TestLatency:
    def test_per_email_aggregate_and_failed_subset(self):
        items = [
            item("em-0001", received_at=BASE, classified_at=BASE + timedelta(seconds=4)),
            item(
                "em-0002",
                status="FAILED",
                primary_category=None,
                secondary_categories=(),
                sensitivity=(),
                received_at=BASE,
                classified_at=BASE + timedelta(seconds=10),
            ),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        per_email = {e["message_id"]: e["seconds"] for e in report["latency"]["per_email"]}
        assert per_email["em-0001"] == 4.0
        assert per_email["em-0002"] == 10.0
        assert report["latency"]["aggregate"]["count"] == 2
        assert report["latency"]["aggregate"]["mean_seconds"] == 7.0
        failed = report["latency"]["failed_subset"]
        assert failed["count"] == 1
        assert failed["mean_seconds"] == 10.0


class TestOtherRate:
    def test_other_rate_and_no_floor_cleared_share(self):
        items = [
            item(
                "em-0002",
                primary_category="OTHER",
                requires_human_review=True,
                queue_reason="no_category_cleared_floor",
            ),
            item("em-0003", primary_category="PAYMENT_BILLING"),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        assert report["other_rate"]["other_count"] == 1
        assert report["other_rate"]["processed"] == 2
        assert report["other_rate"]["share"] == 0.5
        assert report["other_rate"]["no_category_floor_cleared_count"] == 1
        assert report["other_rate"]["no_category_floor_cleared_share"] == 1.0


class TestVersionAttribution:
    def test_all_five_versions_stated(self):
        report = compute_metrics([item()], expected_map(), dataset_version="inbox_small_v1")
        versions = report["versions"]
        assert versions["dataset_version"] == "inbox_small_v1"
        assert versions["question_set_version"] == "qs-1"
        assert versions["threshold_set_version"] == "th-1"
        assert versions["engine_version"] == "eng-1"
        assert versions["classifier_version"] == "cv-1"

    def test_differing_config_versions_identifiable(self):
        first = compute_metrics([item()], expected_map(), dataset_version="d")
        second = compute_metrics(
            [replace(item(), threshold_set_version="th-2")],
            expected_map(),
            dataset_version="d",
        )
        assert (
            first["versions"]["threshold_set_version"]
            != second["versions"]["threshold_set_version"]
        )


class TestAttachmentGap:
    def test_gap_stated_with_affected_count(self):
        items = [
            item("em-0001", attachment_statuses=("extracted", "not_text_extractable")),
            item("em-0002", attachment_statuses=()),
        ]
        report = compute_metrics(items, expected_map(), dataset_version="d")
        limitations = report["limitations"]
        assert limitations["non_text_attachments_excluded"] is True
        assert limitations["statement"]
        assert limitations["affected_attachment_count"] == 1


class TestSeededPipelineRun:
    def test_metrics_over_fixture_run(self, tmp_path):
        repo, run_report = seeded_repo(tmp_path)
        rows = _stored_rows(repo)
        items = [item_from_row(row, att) for row, att in rows]
        report = compute_metrics(items, expected_map(), dataset_version="inbox_small_v1")
        assert report["accuracy"]["denominator"] == run_report.processed == 4
        assert len(report["per_category"]) == 16
        assert report["versions"]["dataset_version"] == "inbox_small_v1"
        # Report is JSON-serializable for the API surface.
        json.dumps(report)

    def test_pipeline_seeded_corrections_never_rewrite_truth(self, tmp_path):
        repo, _ = seeded_repo(tmp_path)
        rows = _stored_rows(repo)
        items = [item_from_row(row, att) for row, att in rows]
        before = compute_metrics(items, expected_map(), dataset_version="d")
        target = repo._conn.execute(
            "SELECT email_id FROM emails ORDER BY rowid LIMIT 1"
        ).fetchone()
        history = repo.get_classification_history(target["email_id"])
        repo.append_review(
            history[-1].classification_id,
            "CORRECTED",
            "reviewer-1",
            [
                {
                    "dimension": "primary_category",
                    "operation": "set",
                    "original_value": "CLAIM_NEW",
                    "corrected_value": "OTHER",
                }
            ],
        )
        rows_after = _stored_rows(repo)
        items_after = [item_from_row(row, att) for row, att in rows_after]
        after = compute_metrics(items_after, expected_map(), dataset_version="d")
        assert after["accuracy"] == before["accuracy"]
