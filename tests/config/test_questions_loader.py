"""Work unit 6 — versioned 28-question set loader (RED tests)."""

from pathlib import Path

import pytest


def write_yaml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "questions.yaml"
    path.write_text(text, encoding="utf-8")
    return path


_PRIMARY = [
    "NEW_LEAD",
    "QUOTE_REQUEST",
    "NEW_POLICY",
    "POLICY_RENEWAL",
    "POLICY_CHANGE",
    "POLICY_CANCELLATION",
    "CLAIM_NEW",
    "CLAIM_UPDATE",
    "CLAIM_DOCUMENTATION",
    "PAYMENT_BILLING",
    "COMPLAINT",
    "FRAUD_SUSPICION",
    "LEGAL",
    "REGULATORY",
    "PARTNERSHIP",
    "OTHER",
]

EXPECTED_QUESTION_IDS = (
    {f"primary_category/{label}" for label in _PRIMARY}
    | {
        f"sensitivity/{label}"
        for label in (
            "PUBLIC",
            "INTERNAL",
            "CONFIDENTIAL",
            "HIGHLY_CONFIDENTIAL",
            "PERSONAL_DATA",
            "SENSITIVE_PERSONAL_DATA",
        )
    }
    | {
        f"action/{label}"
        for label in (
            "NO_ACTION",
            "REPLY_REQUIRED",
            "DOCUMENT_REQUIRED",
            "APPROVAL_REQUIRED",
            "ESCALATE",
            "URGENT",
        )
    }
)

DISAMBIGUATION_PAIRS = [
    ("COMPLAINT", "LEGAL"),
    ("CLAIM_NEW", "CLAIM_UPDATE"),
    ("CLAIM_NEW", "CLAIM_DOCUMENTATION"),
    ("CLAIM_UPDATE", "CLAIM_DOCUMENTATION"),
    ("NEW_LEAD", "QUOTE_REQUEST"),
]

DEFERRED_LABELS = [
    "CLAIM_PAYMENT",
    "CLAIM_REJECTION",
    "UNDERWRITING",
    "BROKER_AGENT",
    "REINSURANCE",
    "SUPPLIER",
]


class TestLoadValid:
    def test_exactly_28_questions_one_per_mvp_label(self, tmp_path):
        from email_classifier.config.loader import load_questions

        qs = load_questions(write_yaml(tmp_path, MINIMAL_VALID))
        assert len(qs.questions) == 28
        assert {q.question_id for q in qs.questions} == EXPECTED_QUESTION_IDS

    def test_each_question_is_noul_with_instructions_and_criteria(self, tmp_path):
        from email_classifier.config.loader import load_questions

        qs = load_questions(write_yaml(tmp_path, MINIMAL_VALID))
        for q in qs.questions:
            assert q.type == "noul"
            assert q.instructions.strip()
            assert q.criteria_true.strip()
            assert q.criteria_false.strip()

    def test_shipped_questions_yaml_loads_with_28_questions(self):
        from email_classifier.config.loader import load_questions

        qs = load_questions("src/email_classifier/config/questions.yaml")
        assert len(qs.questions) == 28
        assert {q.question_id for q in qs.questions} == EXPECTED_QUESTION_IDS

    def test_version_reported_as_sha256_prefix(self, tmp_path):
        from email_classifier.config.loader import load_questions

        qs = load_questions(write_yaml(tmp_path, MINIMAL_VALID))
        assert len(qs.version) == 8
        int(qs.version, 16)  # hex

    def test_version_bumps_when_wording_changes(self, tmp_path):
        from email_classifier.config.loader import load_questions

        v1 = load_questions(write_yaml(tmp_path, MINIMAL_VALID)).version
        changed = MINIMAL_VALID.replace("the email", "the message", 1)
        v2 = load_questions(write_yaml(tmp_path, changed)).version
        assert v2 != v1

    def test_disambiguation_criteria_present(self):
        from email_classifier.config.loader import load_questions

        qs = load_questions("src/email_classifier/config/questions.yaml")
        by_id = {q.question_id: q for q in qs.questions}
        for a, b in DISAMBIGUATION_PAIRS:
            qa, qb = by_id[f"primary_category/{a}"], by_id[f"primary_category/{b}"]
            # Each question of a pair must reference its counterpart by label
            # in its true or false criteria (the boundary is explicit).
            text_a = qa.criteria_true + " " + qa.criteria_false
            text_b = qb.criteria_true + " " + qb.criteria_false
            assert (
                a.replace("_", " ").lower() in text_b.lower()
                or b.replace("_", " ").lower() in text_a.lower()
            ), f"no disambiguation criteria between {a} and {b}"


class TestLoadTimeValidation:
    @pytest.mark.parametrize("label", DEFERRED_LABELS)
    def test_deferred_label_rejected_naming_it(self, tmp_path, label):
        from email_classifier.config.loader import ConfigError, load_questions

        injected = MINIMAL_VALID.replace(
            "questions:",
            f"questions:\n  - question_id: primary_category/{label}\n"
            f"    type: noul\n    instructions: test\n"
            f"    criteria_true: test\n    criteria_false: test\n",
            1,
        )
        with pytest.raises(ConfigError) as excinfo:
            load_questions(write_yaml(tmp_path, injected))
        assert label in str(excinfo.value)

    def test_missing_label_rejected(self, tmp_path):
        from email_classifier.config.loader import ConfigError, load_questions

        missing_one = MINIMAL_VALID.replace("  - question_id: primary_category/OTHER\n", "", 1)
        with pytest.raises(ConfigError) as excinfo:
            load_questions(write_yaml(tmp_path, missing_one))
        assert "OTHER" in str(excinfo.value)

    def test_wrong_question_count_rejected(self, tmp_path):
        from email_classifier.config.loader import ConfigError, load_questions

        dup = MINIMAL_VALID.replace(
            "  - question_id: primary_category/OTHER\n",
            "  - question_id: primary_category/OTHER\n  - question_id: primary_category/OTHER\n",
            1,
        )
        with pytest.raises(ConfigError):
            load_questions(write_yaml(tmp_path, dup))

    def test_non_noul_type_rejected(self, tmp_path):
        from email_classifier.config.loader import ConfigError, load_questions

        bad = MINIMAL_VALID.replace(
            "  - question_id: primary_category/OTHER\n    type: noul\n",
            "  - question_id: primary_category/OTHER\n    type: freeform\n",
            1,
        )
        with pytest.raises(ConfigError):
            load_questions(write_yaml(tmp_path, bad))

    def test_missing_criteria_rejected(self, tmp_path):
        from email_classifier.config.loader import ConfigError, load_questions

        bad = MINIMAL_VALID.replace(
            "  - question_id: primary_category/OTHER\n"
            "    type: noul\n"
            "    instructions: Does the email belong to OTHER?\n"
            "    criteria_true: matches OTHER\n"
            "    criteria_false: does not match OTHER\n",
            "  - question_id: primary_category/OTHER\n    type: noul\n"
            "    instructions: Does the email belong to OTHER?\n",
            1,
        )
        with pytest.raises(ConfigError):
            load_questions(write_yaml(tmp_path, bad))


class TestStoredVersionStability:
    def test_loaded_version_is_content_addressed(self, tmp_path):
        from email_classifier.config.loader import load_questions

        # Same bytes -> same version; stored classifications keep the version
        # they were produced under because the version derives from the file.
        a = load_questions(write_yaml(tmp_path, MINIMAL_VALID)).version
        b = load_questions(write_yaml(tmp_path, MINIMAL_VALID)).version
        assert a == b


MINIMAL_VALID = (
    """\
questions:
"""
    + "\n".join(
        f"""  - question_id: primary_category/{label}
    type: noul
    instructions: Does the email belong to {label}?
    criteria_true: matches {label}
    criteria_false: does not match {label}"""
        for label in [
            "NEW_LEAD",
            "QUOTE_REQUEST",
            "NEW_POLICY",
            "POLICY_RENEWAL",
            "POLICY_CHANGE",
            "POLICY_CANCELLATION",
            "CLAIM_NEW",
            "CLAIM_UPDATE",
            "CLAIM_DOCUMENTATION",
            "PAYMENT_BILLING",
            "COMPLAINT",
            "FRAUD_SUSPICION",
            "LEGAL",
            "REGULATORY",
            "PARTNERSHIP",
            "OTHER",
        ]
    )
    + "\n"
    + "\n".join(
        f"""  - question_id: sensitivity/{label}
    type: noul
    instructions: Is the email {label}?
    criteria_true: is {label}
    criteria_false: is not {label}"""
        for label in [
            "PUBLIC",
            "INTERNAL",
            "CONFIDENTIAL",
            "HIGHLY_CONFIDENTIAL",
            "PERSONAL_DATA",
            "SENSITIVE_PERSONAL_DATA",
        ]
    )
    + "\n"
    + "\n".join(
        f"""  - question_id: action/{label}
    type: noul
    instructions: Does the email require {label}?
    criteria_true: requires {label}
    criteria_false: does not require {label}"""
        for label in [
            "NO_ACTION",
            "REPLY_REQUIRED",
            "DOCUMENT_REQUIRED",
            "APPROVAL_REQUIRED",
            "ESCALATE",
            "URGENT",
        ]
    )
    + "\n"
)
