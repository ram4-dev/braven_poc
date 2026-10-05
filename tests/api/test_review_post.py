"""Work unit 14 — review POST + replay endpoint (RED tests).

Acceptance scenarios from the human-review delta spec:
- Confirmation (CONFIRMED stores a review record and the email leaves the queue).
- Single-dimension correction (one delta; other dimensions unchanged).
- Adding a secondary label / removing a sensitivity label (multi-label ops).
- Delta validation against the frozen label set (unknown label -> 422).
- Queue entry closed on review.
- Correction stored outside ground truth (original classification record
  unchanged; only review history grows).
- Replay-triggering route rejected for unknown threshold version (422/404).
- POST /api/replay produces new append-only rows via the pure replay path.
"""

from dataclasses import replace

from fastapi.testclient import TestClient
from tests.api.conftest import ScriptedScorer, fixture_dataset, make_questions

from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.domain.models import ThresholdConfig
from email_classifier.pipeline.pipeline import Pipeline


def seed_queued(tmp_path, name="db.sqlite3"):
    """Seed with a guaranteed queue entry: em-0004 LEGAL at 0.80 (>= floor
    0.40, < auto 0.95) -> sensitive_signal queue entry."""
    repo = SqliteRepository(tmp_path / name)
    scorer = ScriptedScorer(
        scores_by_message_id={
            "em-0004": {
                "primary_category/CLAIM_NEW": 0.75,
                "sensitivity/PERSONAL_DATA": 0.70,
            }
        }
    )
    pipeline = Pipeline(
        source=fixture_dataset(),
        engine=scorer,
        repository=repo,
        thresholds=ThresholdConfig.mvp(),
        questions=make_questions(),
    )
    report = pipeline.run()
    app_module = __import__("email_classifier.api.app", fromlist=["create_app"])
    client = TestClient(app_module.create_app(repository=repo))
    return client, repo, report


def queue_ids(client):
    return {entry["classification_id"] for entry in client.get("/api/review-queue").json()["queue"]}


def sensitive_queue_id(client):
    """The em-0004 queue entry (queued with reason sensitive_signal)."""
    entries = [
        entry
        for entry in client.get("/api/review-queue").json()["queue"]
        if entry["queue_reason"] == "sensitive_signal"
    ]
    assert entries, "expected a sensitive_signal queue entry"
    return entries[0]["classification_id"]


class TestConfirmClosesQueue:
    def test_confirmed_review_stored_and_queue_entry_closed(self, tmp_path):
        client, repo, _report = seed_queued(tmp_path)
        queue_before = queue_ids(client)
        assert queue_before, "expected a seeded queue entry"

        classification_id = next(iter(queue_before))
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CONFIRMED",
                "reviewer_id": "reviewer-1",
            },
        )
        assert response.status_code in (200, 201), response.text
        assert response.json()["review_id"]

        # The reviewed classification leaves the queue.
        assert classification_id not in queue_ids(client)

        # The review record is retrievable through the detail route.
        stored = repo.get_classification(classification_id)
        detail = client.get(f"/api/emails/{stored.email_id}").json()
        assert detail["reviews"][-1]["status"] == "CONFIRMED"
        assert detail["reviews"][-1]["reviewer_id"] == "reviewer-1"

    def test_review_of_unknown_classification_404(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": "does-not-exist",
                "status": "CONFIRMED",
                "reviewer_id": "reviewer-1",
            },
        )
        assert response.status_code == 404


class TestCorrectPerDimension:
    def test_single_dimension_correction_other_dimensions_unchanged(self, tmp_path):
        client, repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        stored = repo.get_classification(classification_id)
        original_priority = stored.priority.value if stored.priority else None
        original_sensitivity = [s.value for s in stored.sensitivity]

        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-2",
                "deltas": [
                    {
                        "dimension": "primary_category",
                        "operation": "set",
                        "original_value": stored.primary_category.value
                        if stored.primary_category
                        else None,
                        "corrected_value": "CLAIM_NEW",
                    }
                ],
            },
        )
        assert response.status_code in (200, 201), response.text

        current = repo.get_current_classification(stored.email_id)
        assert current.primary_category.value == "CLAIM_NEW"
        assert [s.value for s in current.sensitivity] == original_sensitivity
        assert (current.priority.value if current.priority else None) == original_priority

    def test_add_secondary_and_remove_sensitivity(self, tmp_path):
        client, repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        stored = repo.get_classification(classification_id)
        existing_secondary = [
            c.value for c in stored.secondary_categories
        ]

        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-3",
                "deltas": [
                    {
                        "dimension": "secondary_categories",
                        "operation": "add",
                        "corrected_value": "COMPLAINT",
                    },
                    {
                        "dimension": "secondary_categories",
                        "operation": "add",
                        "corrected_value": "PAYMENT_BILLING",
                    },
                    {
                        "dimension": "sensitivity",
                        "operation": "remove",
                        "original_value": stored.sensitivity[0].value,
                    },
                ],
            },
        )
        assert response.status_code in (200, 201), response.text

        current = repo.get_current_classification(stored.email_id)
        secondary_values = [c.value for c in current.secondary_categories]
        for label in existing_secondary:
            assert label in secondary_values, "existing secondary preserved"
        assert "COMPLAINT" in secondary_values
        assert "PAYMENT_BILLING" in secondary_values
        assert stored.sensitivity[0].value not in [s.value for s in current.sensitivity]

    def test_unknown_label_rejected_422(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-4",
                "deltas": [
                    {
                        "dimension": "primary_category",
                        "operation": "set",
                        "corrected_value": "TOTALLY_FAKE_LABEL",
                    }
                ],
            },
        )
        assert response.status_code == 422

    def test_unknown_dimension_rejected_422(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-4",
                "deltas": [
                    {
                        "dimension": "tone_of_voice",
                        "operation": "set",
                        "corrected_value": "LEGAL",
                    }
                ],
            },
        )
        assert response.status_code == 422

    def test_unknown_operation_rejected_422(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-4",
                "deltas": [
                    {
                        "dimension": "primary_category",
                        "operation": "merge",
                        "corrected_value": "LEGAL",
                    }
                ],
            },
        )
        assert response.status_code == 422

    def test_unknown_status_rejected_422(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "OVERRULED",
                "reviewer_id": "reviewer-4",
            },
        )
        assert response.status_code == 422


class TestCorrectionOutsideGroundTruth:
    def test_original_classification_record_unchanged_after_correction(self, tmp_path):
        client, repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        before = repo.get_classification(classification_id)

        client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-5",
                "deltas": [
                    {
                        "dimension": "primary_category",
                        "operation": "set",
                        "original_value": before.primary_category.value,
                        "corrected_value": "CLAIM_NEW",
                    }
                ],
            },
        )

        after = repo.get_classification(classification_id)
        # The stored automated record is byte-identical: corrections live in
        # review history, never rewrite the classification (append-only).
        assert after.primary_category.value == before.primary_category.value
        assert after.classifier_version == before.classifier_version
        assert after.raw_scores == before.raw_scores
        assert after.band == before.band

        # The dataset's expected ground truth is untouched (frozen source).
        expected = fixture_dataset().expected_for("em-0004")
        assert expected["primary_category"] == "LEGAL"

    def test_review_history_grows_without_new_classification_rows(self, tmp_path):
        client, repo, _report = seed_queued(tmp_path)
        classification_id = sensitive_queue_id(client)
        counts_before = repo.counts()

        client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CONFIRMED",
                "reviewer_id": "reviewer-6",
            },
        )

        counts_after = repo.counts()
        assert counts_after["human_reviews"] == counts_before["human_reviews"] + 1
        assert counts_after["classifications"] == counts_before["classifications"]


class TestReplayEndpoint:
    def test_unknown_threshold_version_rejected(self, tmp_path):
        client, _repo, _report = seed_queued(tmp_path)
        response = client.post(
            "/api/replay", json={"threshold_set_version": "th-unknown-v99"}
        )
        assert response.status_code in (422, 404), response.text

    def test_replay_with_new_thresholds_appends_rows(self, tmp_path):
        client, repo, report = seed_queued(tmp_path, name="db-replay.sqlite3")
        t2 = replace(ThresholdConfig.mvp(), version="th-t2")
        inline = {
            "default": {
                "auto_threshold": t2.default_auto_threshold,
                "review_floor": t2.default_review_floor,
            },
            "elevated": [
                {
                    "dimension": lt.dimension,
                    "label": lt.label,
                    "auto_threshold": lt.auto_threshold,
                    "review_floor": lt.review_floor,
                }
                for lt in t2.elevated.values()
            ],
        }
        counts_before = repo.counts()["classifications"]

        response = client.post(
            "/api/replay",
            json={"threshold_set_version": "th-t2", "thresholds": inline},
        )
        assert response.status_code in (200, 201), response.text

        # New append-only rows: one per classified email.
        assert repo.counts()["classifications"] > counts_before
        for email_id in report.email_ids:
            history = repo.get_classification_history(email_id)
            assert any(
                rec.threshold_set_version == "th-t2" for rec in history
            ), "expected a T2 record appended"
            # T1 record still retrievable (append-only history).
            assert any(
                rec.threshold_set_version == "th-mvp" for rec in history
            )
