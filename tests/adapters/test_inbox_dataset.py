"""Work unit 7 — dataset-backed inbox adapter (RED tests).

Acceptance scenarios come from the email-ingestion spec: complete normalized
email, missing optional fields, attachment statuses, idempotent replay,
non-synthetic rejection (reported, never silently skipped), empty source.
"""

import json
from pathlib import Path

FIXTURE = Path("tests/fixtures/inbox_small.json")


def load_dataset():
    from email_classifier.adapters.inbox_dataset import InboxDatasetSource

    return InboxDatasetSource.from_file(FIXTURE)


def write_dataset(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "inbox.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


BASE_EMAIL = {
    "message_id": "em-x1",
    "sender": "a@example.com",
    "recipients": ["seguros@ejemplo.com"],
    "subject": "Consulta",
    "body": "Consulta general.",
    "thread_id": None,
    "received_at": "2026-10-05T14:32:00Z",
    "attachments": [],
    "expected": {
        "primary_category": "OTHER",
        "secondary_categories": [],
        "sensitivity": ["PUBLIC"],
        "actions": ["NO_ACTION"],
        "priority": "NORMAL",
    },
}


class TestNormalizedIntake:
    def test_complete_email_normalized(self):
        source = load_dataset()
        emails = source.list_emails()
        assert len(emails) == 4

        first = next(e for e in emails if e.message_id == "em-0001")
        assert first.subject == "Reclamo por choque en Av. Rivadavia"
        assert first.sender == "cliente@example.com"
        assert first.recipients == ["seguros@ejemplo.com"]
        assert "choque" in first.body
        assert first.thread_id == "th-0001"
        assert first.received_at.isoformat() == "2026-10-05T14:32:00+00:00"
        assert len(first.attachments) == 2

    def test_missing_optional_thread_id_ingested(self, tmp_path):
        from email_classifier.adapters.inbox_dataset import InboxDatasetSource

        payload = {"dataset_version": "v", "emails": [BASE_EMAIL]}
        source = InboxDatasetSource.from_file(write_dataset(tmp_path, payload))
        emails = source.list_emails()
        assert len(emails) == 1
        assert emails[0].thread_id is None

    def test_expected_labels_reported(self):
        source = load_dataset()
        expected = source.expected_for("em-0001")
        assert expected["primary_category"] == "CLAIM_NEW"
        assert "PERSONAL_DATA" in expected["sensitivity"]


class TestAttachmentStatus:
    def test_text_extractable_attachment(self):
        source = load_dataset()
        first = next(e for e in source.list_emails() if e.message_id == "em-0001")
        att = next(a for a in first.attachments if a.filename == "denuncia.pdf")
        assert att.status.value == "extracted"
        assert "Denuncia policial" in (att.extracted_text or "")

    def test_image_only_attachment_not_text_extractable(self):
        source = load_dataset()
        first = next(e for e in source.list_emails() if e.message_id == "em-0001")
        att = next(a for a in first.attachments if a.filename == "foto_danio.jpg")
        assert att.status.value == "not_text_extractable"
        assert att.extracted_text is None


class TestRejectionAndIdempotency:
    def test_non_synthetic_item_rejected_and_reported(self, tmp_path):
        payload = {
            "dataset_version": "v",
            "emails": [
                BASE_EMAIL,
                {
                    **BASE_EMAIL,
                    "message_id": "em-real-1",
                    "synthetic": False,
                },
            ],
        }
        from email_classifier.adapters.inbox_dataset import InboxDatasetSource

        source = InboxDatasetSource.from_file(write_dataset(tmp_path, payload))
        result = source.ingest()
        # Rejected item is reported, never silently skipped.
        assert list(result.rejected) == ["em-real-1"]
        assert result.ingested_count == 1

    def test_ingest_replayed_one_record_per_message_id(self, tmp_path):
        from email_classifier.adapters.inbox_dataset import InboxDatasetSource

        payload = {"dataset_version": "v", "emails": [BASE_EMAIL]}
        source = InboxDatasetSource.from_file(write_dataset(tmp_path, payload))

        r1 = source.ingest()
        assert r1.ingested_count == 1
        # Replay: same source ingested again -> no duplicate, no re-ingest.
        r2 = source.ingest()
        assert r2.ingested_count == 0
        assert source.seen_message_ids() == {"em-x1"}

    def test_empty_source_zero_ingested_no_error(self, tmp_path):
        from email_classifier.adapters.inbox_dataset import InboxDatasetSource

        payload = {"dataset_version": "v", "emails": []}
        source = InboxDatasetSource.from_file(write_dataset(tmp_path, payload))
        result = source.ingest()
        assert result.ingested_count == 0
        assert list(result.rejected) == []
