"""Work unit 13 — read API (RED tests).

Acceptance scenarios from the classification-dashboard delta spec:
- Classified email listing (complete dimension set + band, nothing omitted).
- Unclassified (failed) email visible as unclassified, no invented labels.
- Current values after review (corrected values current, originals retrievable).
- Unreviewed values shown unchanged.
- Decision evidence visible (raw scores + applied thresholds + composite
  classifier version, zero engine calls).
- Sensitive non-auto label evidence (score, auto threshold, review floor,
  routing decision).
Plus human-review queue scenarios: listing the queue + filtering by reason.
And GET /api/health.
"""


import pytest
from fastapi.testclient import TestClient
from tests.api.conftest import ScriptedScorer, fixture_dataset, seed

from email_classifier.adapters.sqlite_repo import SqliteRepository

ALL_DIMENSION_FIELDS = {
    "primary_category",
    "secondary_categories",
    "sensitivity",
    "actions",
    "priority",
}


def make_client(tmp_path):
    from email_classifier.api.app import create_app

    repo = SqliteRepository(tmp_path / "db.sqlite3")
    report, _ = seed(repo)
    app = create_app(repository=repo)
    return TestClient(app), repo, report


def make_client_raw(tmp_path):
    from email_classifier.api.app import create_app

    repo = SqliteRepository(tmp_path / "db.sqlite3")
    app = create_app(repository=repo)
    return TestClient(app), repo


class TestHealth:
    def test_health_ok(self, tmp_path):
        client, _repo = make_client_raw(tmp_path)
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestListing:
    def test_every_stored_email_listed_with_complete_dimensions(self, tmp_path):
        client, _repo, report = make_client(tmp_path)
        response = client.get("/api/emails")
        assert response.status_code == 200
        entries = response.json()["emails"]
        assert len(entries) == report.ingested == 4
        by_message = {e["message_id"]: e for e in entries}
        assert set(by_message) == {"em-0001", "em-0002", "em-0003", "em-0004"}
        for entry in entries:
            assert ALL_DIMENSION_FIELDS <= set(entry)
            assert entry["band"] in ("AUTOMATIC", "UNCERTAIN", "HUMAN_REVIEW")
            assert isinstance(entry["requires_human_review"], bool)
            assert entry["classifier_version"]
            assert entry["classified_at"]
            assert entry["status"] in ("CLASSIFIED", "FAILED")

    def test_confidence_and_dimensions_are_stored_values(self, tmp_path):
        client, repo, report = make_client(tmp_path)
        entries = client.get("/api/emails").json()["emails"]
        by_message = {e["message_id"]: e for e in entries}
        stored = {
            repo.get_email(email_id).message_id: repo.get_current_classification(email_id)
            for email_id in report.email_ids
        }
        for message_id, record in stored.items():
            entry = by_message[message_id]
            assert entry["confidence"] == record.confidence
            assert entry["primary_category"] == (
                record.primary_category.value if record.primary_category else None
            )
            assert entry["secondary_categories"] == [
                c.value for c in record.secondary_categories
            ]
            assert entry["sensitivity"] == [s.value for s in record.sensitivity]
            assert entry["actions"] == [a.value for a in record.actions]
            assert entry["priority"] == (
                record.priority.value if record.priority else None
            )

    def test_unreviewed_values_shown_unchanged(self, tmp_path):
        client, _repo, report = make_client(tmp_path)
        listing = client.get("/api/emails").json()["emails"]
        stored = {
            repo_message: repo_record
            for repo_message, repo_record in (
                (
                    _repo.get_email(email_id).message_id,
                    _repo.get_current_classification(email_id),
                )
                for email_id in report.email_ids
            )
        }
        by_message = {e["message_id"]: e for e in listing}
        for message_id, record in stored.items():
            assert by_message[message_id]["primary_category"] == (
                record.primary_category.value if record.primary_category else None
            )

    def test_corrected_values_shown_as_current_with_originals_retrievable(
        self, tmp_path
    ):
        client, repo, report = make_client(tmp_path)
        email_id = report.email_ids[0]
        automated = repo.get_current_classification(email_id).primary_category.value
        classification_id = repo.get_current_classification(email_id).classification_id
        review_response = client.post(
            "/api/reviews",
            json={
                "classification_id": classification_id,
                "status": "CORRECTED",
                "reviewer_id": "reviewer-7",
                "deltas": [
                    {
                        "dimension": "primary_category",
                        "operation": "set",
                        "original_value": automated,
                        "corrected_value": "CLAIM_UPDATE",
                    }
                ],
            },
        )
        assert review_response.status_code in (200, 201), review_response.text

        listing = client.get("/api/emails").json()["emails"]
        by_message = {e["message_id"]: e for e in listing}
        corrected = by_message["em-0001"]
        assert corrected["primary_category"] == "CLAIM_UPDATE"

        detail = client.get(f"/api/emails/{email_id}").json()
        assert detail["current"]["primary_category"] == "CLAIM_UPDATE"
        originals = detail["originals"]
        assert originals["primary_category"] == automated
        assert originals["primary_category"] != "CLAIM_UPDATE"
        assert detail["reviews"][-1]["reviewer_id"] == "reviewer-7"

    def test_unclassified_email_visible_as_unclassified(self, tmp_path):
        from tests.api.conftest import make_questions

        from email_classifier.pipeline.pipeline import Pipeline

        repo = SqliteRepository(tmp_path / "db-fail.sqlite3")
        scorer = ScriptedScorer(failing={"em-0002"})
        pipeline = Pipeline(
            source=fixture_dataset(),
            engine=scorer,
            repository=repo,
            thresholds=__import__(
                "email_classifier.domain.models", fromlist=["ThresholdConfig"]
            ).ThresholdConfig.mvp(),
            questions=make_questions(),
        )
        pipeline.run()

        from email_classifier.api.app import create_app

        client = TestClient(create_app(repository=repo))
        entries = client.get("/api/emails").json()["emails"]
        failed = [e for e in entries if e["message_id"] == "em-0002"]
        assert len(failed) == 1
        entry = failed[0]
        assert entry["status"] == "FAILED"
        assert entry["primary_category"] is None
        assert entry["sensitivity"] == []
        assert entry["confidence"] is None


class TestDetail:
    def test_decision_evidence_visible_without_engine(self, tmp_path):
        client, repo, report = make_client(tmp_path)
        email_id = report.email_ids[0]
        stored = repo.get_current_classification(email_id)

        detail = client.get(f"/api/emails/{email_id}").json()
        assert detail["current"]["raw_scores"] == stored.raw_scores
        assert detail["current"]["classifier_version"] == stored.classifier_version
        assert detail["current"]["threshold_set_version"] == (
            stored.threshold_set_version
        )
        assert detail["current"]["engine_version"] == stored.engine_version
        assert len(detail["current"]["applied_thresholds"]) == len(stored.raw_scores)
        for key in stored.raw_scores:
            assert detail["current"]["applied_thresholds"][key] == pytest.approx(
                0.95 if key.endswith(("FRAUD_SUSPICION", "LEGAL", "HIGHLY_CONFIDENTIAL"))
                else 0.90
            )

    def test_sensitive_non_auto_label_evidence(self, tmp_path):
        # em-0004 is a legal demand: force LEGAL just below its 0.95 auto bar
        # and above its 0.40 review floor so it routes to review.
        from tests.api.conftest import make_questions

        from email_classifier.pipeline.pipeline import Pipeline

        repo = SqliteRepository(tmp_path / "db-sens.sqlite3")
        scores = {
            "primary_category/LEGAL": 0.80,
            "sensitivity/HIGHLY_CONFIDENTIAL": 0.42,
        }
        scorer = ScriptedScorer(scores_by_message_id={"em-0004": scores})
        pipeline = Pipeline(
            source=fixture_dataset(),
            engine=scorer,
            repository=repo,
            thresholds=__import__(
                "email_classifier.domain.models", fromlist=["ThresholdConfig"]
            ).ThresholdConfig.mvp(),
            questions=make_questions(),
        )
        pipeline.run()

        from email_classifier.api.app import create_app

        client = TestClient(create_app(repository=repo))
        entries = client.get("/api/emails").json()["emails"]
        legal_entry = next(e for e in entries if e["message_id"] == "em-0004")
        email_id = legal_entry["email_id"]
        detail = client.get(f"/api/emails/{email_id}").json()

        label_evidence = {
            f"{label['dimension']}/{label['label']}": label
            for label in detail["labels"]
        }
        legal = label_evidence["primary_category/LEGAL"]
        assert legal["score"] == pytest.approx(0.80)
        assert legal["auto_threshold"] == pytest.approx(0.95)
        assert legal["review_floor"] == pytest.approx(0.40)
        assert legal["selected"] is False
        assert legal["routed_to_review"] is True

        hc = label_evidence["sensitivity/HIGHLY_CONFIDENTIAL"]
        assert hc["score"] == pytest.approx(0.42)
        assert hc["review_floor"] == pytest.approx(0.40)

    def test_unknown_email_404(self, tmp_path):
        client, _repo = make_client_raw(tmp_path)
        assert client.get("/api/emails/nope").status_code == 404


class TestReviewQueue:
    def test_queue_listing_and_reason_filter(self, tmp_path):
        # LEGAL at 0.80 (>= floor 0.40, < auto 0.95) forces a sensitive-signal
        # queue entry for em-0004; the fake scorer's other emails may or may
        # not queue, so assertions are relative.
        from tests.api.conftest import make_questions

        from email_classifier.pipeline.pipeline import Pipeline

        repo = SqliteRepository(tmp_path / "db-queue.sqlite3")
        scores = {"primary_category/LEGAL": 0.80}
        scorer = ScriptedScorer(scores_by_message_id={"em-0004": scores})
        pipeline = Pipeline(
            source=fixture_dataset(),
            engine=scorer,
            repository=repo,
            thresholds=__import__(
                "email_classifier.domain.models", fromlist=["ThresholdConfig"]
            ).ThresholdConfig.mvp(),
            questions=make_questions(),
        )
        pipeline.run()

        from email_classifier.api.app import create_app

        client = TestClient(create_app(repository=repo))
        queue = client.get("/api/review-queue").json()["queue"]
        assert len(queue) >= 1
        reasons = {entry["queue_reason"] for entry in queue}
        assert "sensitive_signal" in reasons
        for entry in queue:
            assert entry["message_id"]
            assert entry["classification_id"]
            assert "dimensions" in entry
            assert "band" in entry and "confidence" in entry

        filtered = client.get(
            "/api/review-queue", params={"reason": "sensitive_signal"}
        ).json()["queue"]
        assert filtered, "expected at least one sensitive_signal entry"
        assert all(e["queue_reason"] == "sensitive_signal" for e in filtered)
        assert len(filtered) < len(queue) or set(
            e["queue_reason"] for e in queue
        ) == {"sensitive_signal"}
