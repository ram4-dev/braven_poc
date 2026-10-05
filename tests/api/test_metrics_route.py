"""Work unit 15 — GET /api/metrics route (RED tests).

The API surface exposes the classification-metrics report over the stored read
model. Ground truth comes from the dataset's expected labels (never reviewer
corrections), so the app is constructed with the dataset's expected map.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from tests.api.conftest import fixture_dataset, make_questions

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import ThresholdConfig

FIXTURE = Path("tests/fixtures/inbox_small.json")


def fixture_ground_truth():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = {
        item["message_id"]: item.get("expected") or {} for item in data["emails"]
    }
    return expected, data["dataset_version"]


def seeded_client(tmp_path):
    from email_classifier.pipeline.pipeline import Pipeline

    repo = SqliteRepository(tmp_path / "db.sqlite3")
    pipeline = Pipeline(
        source=fixture_dataset(),
        engine=FakeDeterministicScorer(),
        repository=repo,
        thresholds=ThresholdConfig.mvp(),
        questions=make_questions(),
    )
    pipeline.run()
    expected, dataset_version = fixture_ground_truth()
    app_module = __import__("email_classifier.api.app", fromlist=["create_app"])
    client = TestClient(
        app_module.create_app(
            repository=repo,
            expected_labels=expected,
            dataset_version=dataset_version,
        )
    )
    return client, repo


class TestMetricsRoute:
    def test_get_metrics_returns_report(self, tmp_path):
        client, _repo = seeded_client(tmp_path)
        response = client.get("/api/metrics")
        assert response.status_code == 200
        report = response.json()
        assert report["accuracy"]["denominator"] == 4
        assert len(report["per_category"]) == 16
        assert report["versions"]["dataset_version"] == "inbox_small_v1"
        assert report["limitations"]["non_text_attachments_excluded"] is True
        assert report["limitations"]["affected_attachment_count"] == 1

    def test_metrics_use_stored_automated_values_not_corrections(
        self, tmp_path
    ):
        client, repo = seeded_client(tmp_path)
        # Reviewer "rewrites" every primary category; the report must stay
        # computed from the stored automated values + dataset truth.
        row = repo._conn.execute(
            "SELECT email_id FROM emails ORDER BY rowid LIMIT 1"
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
        report = client.get("/api/metrics").json()
        assert report["per_category"]["CLAIM_NEW"]["predicted_count"] >= 1
        # Exactly ONE automated OTHER prediction exists (em-0002, fake
        # scorer). The reviewer's correction to OTHER must NOT add a
        # second one — metrics read stored automated values only.
        assert report["per_category"]["OTHER"]["predicted_count"] == 1
