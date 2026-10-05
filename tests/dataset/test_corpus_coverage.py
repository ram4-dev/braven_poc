"""Coverage proof for the synthetic corpus `datasets/inbox_mvp_v1.json`.

Design D6 + task 10.2: the dataset itself is the frozen ground-truth slice,
so these tests pin its shape and its label coverage against the MVP taxonomy
in `openspec/config.yaml`.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "datasets" / "inbox_mvp_v1.json"
CONFIG_PATH = REPO_ROOT / "openspec" / "config.yaml"

REQUIRED_EMAIL_KEYS = {
    "message_id",
    "sender",
    "recipients",
    "subject",
    "body",
    "thread_id",
    "received_at",
    "attachments",
    "synthetic",
    "expected",
}
REQUIRED_ATTACHMENT_KEYS = {"filename", "mime", "extracted_text", "status"}
REQUIRED_EXPECTED_KEYS = {
    "primary_category",
    "secondary_categories",
    "sensitivity",
    "actions",
    "priority",
}
DEFERRED_CATEGORIES = {
    "CLAIM_PAYMENT",
    "CLAIM_REJECTION",
    "UNDERWRITING",
    "BROKER_AGENT",
    "REINSURANCE",
    "SUPPLIER",
}
MIN_PER_PRIMARY_CATEGORY = 5
MIN_PER_SENSITIVITY = 8
MIN_BOUNDARY_CASES = 15
MIN_IMAGE_ONLY_EMAILS = 4


@pytest.fixture(scope="module")
def taxonomy() -> dict:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return config["taxonomy_mvp"]


@pytest.fixture(scope="module")
def dataset() -> dict:
    assert DATASET_PATH.exists(), f"corpus missing: {DATASET_PATH}"
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def emails(dataset) -> list[dict]:
    return dataset["emails"]


def test_dataset_version_and_schema_shape(dataset, emails):
    assert dataset["dataset_version"] == "v1"
    assert isinstance(emails, list) and len(emails) >= 100
    for email in emails:
        missing = REQUIRED_EMAIL_KEYS - set(email)
        assert not missing, f"{email.get('message_id')}: missing keys {missing}"
        assert isinstance(email["recipients"], list)
        assert isinstance(email["attachments"], list)
        for attachment in email["attachments"]:
            missing = REQUIRED_ATTACHMENT_KEYS - set(attachment)
            assert not missing, (
                f"{email['message_id']}: attachment missing {missing}"
            )
        expected = email["expected"]
        missing = REQUIRED_EXPECTED_KEYS - set(expected)
        assert not missing, f"{email['message_id']}: expected missing {missing}"
        assert isinstance(expected["secondary_categories"], list)
        assert isinstance(expected["sensitivity"], list)
        assert isinstance(expected["actions"], list)


def test_at_least_five_emails_per_primary_category(emails, taxonomy):
    counts: dict[str, int] = {}
    for email in emails:
        counts[email["expected"]["primary_category"]] = (
            counts.get(email["expected"]["primary_category"], 0) + 1
        )
    for category in taxonomy["primary_categories"]:
        assert counts.get(category, 0) >= MIN_PER_PRIMARY_CATEGORY, (
            f"{category}: {counts.get(category, 0)} < {MIN_PER_PRIMARY_CATEGORY}"
        )
    assert set(counts) == set(taxonomy["primary_categories"])


def test_at_least_eight_emails_per_sensitivity_label(emails, taxonomy):
    counts: dict[str, int] = {}
    for email in emails:
        for label in email["expected"]["sensitivity"]:
            counts[label] = counts.get(label, 0) + 1
    for label in taxonomy["sensitivity"]:
        assert counts.get(label, 0) >= MIN_PER_SENSITIVITY, (
            f"{label}: {counts.get(label, 0)} < {MIN_PER_SENSITIVITY}"
        )


def test_at_least_fifteen_boundary_cases(dataset, emails):
    boundary = dataset["boundary_cases"]
    assert len(boundary) >= MIN_BOUNDARY_CASES
    known_ids = {email["message_id"] for email in emails}
    for case in boundary:
        assert case["message_id"] in known_ids, (
            f"boundary case references unknown id {case['message_id']}"
        )
        assert case.get("reason"), (
            f"boundary case {case['message_id']} lacks a documented reason"
        )
    referenced = {case["message_id"] for case in boundary}
    assert len(referenced) == len(boundary), "duplicate boundary message_id"


def test_at_least_four_image_only_attachment_emails(emails):
    image_mimes = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff"}

    def image_only(email: dict) -> bool:
        attachments = email["attachments"]
        if not attachments:
            return False
        return all(
            attachment["mime"] in image_mimes
            and attachment["status"] == "not_text_extractable"
            for attachment in attachments
        )

    assert sum(1 for email in emails if image_only(email)) >= MIN_IMAGE_ONLY_EMAILS


def test_unique_message_ids(emails):
    ids = [email["message_id"] for email in emails]
    assert len(ids) == len(set(ids)), "duplicate message_id in corpus"


def test_no_deferred_categories(emails):
    for email in emails:
        expected = email["expected"]
        used = {expected["primary_category"], *expected["secondary_categories"]}
        leaked = used & DEFERRED_CATEGORIES
        assert not leaked, f"{email['message_id']}: deferred labels {leaked}"


def test_expected_labels_inside_taxonomy(emails, taxonomy):
    primary = set(taxonomy["primary_categories"])
    sensitivities = set(taxonomy["sensitivity"])
    actions = set(taxonomy["actions"])
    priorities = set(taxonomy["priority"])
    for email in emails:
        expected = email["expected"]
        mid = email["message_id"]
        assert expected["primary_category"] in primary, mid
        assert set(expected["secondary_categories"]) <= primary, mid
        assert set(expected["sensitivity"]) <= sensitivities, mid
        assert set(expected["actions"]) <= actions, mid
        assert expected["priority"] in priorities, mid


def test_every_email_marked_synthetic(emails):
    for email in emails:
        assert email["synthetic"] is True, email["message_id"]
