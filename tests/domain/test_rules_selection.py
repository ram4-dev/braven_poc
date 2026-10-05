"""Work unit 4 — selection, implications, precedence (classification-rules RED tests)."""

from email_classifier.domain.models import (
    Action,
    Band,
    PrimaryCategory,
    Priority,
    Sensitivity,
    ThresholdConfig,
)
from email_classifier.domain.rules import decide

DEFAULT = ThresholdConfig.mvp()


def raw(*pairs: tuple[str, float]) -> dict[str, float]:
    return dict(pairs)


class TestConfidence:
    def test_confidence_equals_the_primary_score(self):
        r = decide(
            raw(
                ("primary_category/CLAIM_NEW", 0.96),
                ("primary_category/CLAIM_DOCUMENTATION", 0.81),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        assert r.confidence == 0.96

    def test_per_label_scores_remain_available(self):
        scores_map = raw(
            ("primary_category/CLAIM_NEW", 0.96),
            ("primary_category/CLAIM_DOCUMENTATION", 0.81),
            ("sensitivity/PERSONAL_DATA", 0.70),
        )
        r = decide(scores_map, DEFAULT)
        assert r.raw_scores == scores_map  # verbatim, never replaced by aggregates


class TestSelection:
    def test_multi_category_email(self):
        r = decide(
            raw(
                ("primary_category/CLAIM_DOCUMENTATION", 0.91),
                ("primary_category/CLAIM_NEW", 0.96),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        assert r.secondary_categories == (PrimaryCategory.CLAIM_DOCUMENTATION,)

    def test_secondary_requires_clearing_its_floor(self):
        r = decide(
            raw(
                ("primary_category/CLAIM_NEW", 0.96),
                ("primary_category/CLAIM_DOCUMENTATION", 0.60),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        assert r.secondary_categories == ()

    def test_deterministic_tie_break(self):
        scores_map = raw(
            ("primary_category/CLAIM_DOCUMENTATION", 0.93),
            ("primary_category/CLAIM_NEW", 0.93),
        )
        r1 = decide(scores_map, DEFAULT)
        r2 = decide(dict(scores_map), DEFAULT)
        assert r1.primary_category is r2.primary_category
        assert r1.secondary_categories == r2.secondary_categories
        # Same score for both: the winner's score is the confidence either way.
        assert r1.confidence == 0.93

    def test_no_category_clears_floor_other_plus_review(self):
        r = decide(raw(("primary_category/CLAIM_NEW", 0.50)), DEFAULT)
        assert r.primary_category is PrimaryCategory.OTHER
        assert r.requires_human_review is True
        assert r.queue_reason is not None

    def test_ambiguous_pair_stored_together_when_both_clear_floor(self):
        r = decide(
            raw(
                ("primary_category/COMPLAINT", 0.92),
                ("primary_category/LEGAL", 0.91),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.COMPLAINT
        assert r.secondary_categories == (PrimaryCategory.LEGAL,)
        # The versioned disambiguation precedence is recorded via the config version.
        assert r.threshold_set_version == DEFAULT.version


class TestElevatedAutoThresholdSelection:
    """Selection eligibility uses each label's OWN auto threshold, not the default."""

    def test_legal_below_its_elevated_auto_threshold_is_not_selected(self):
        # LEGAL auto threshold is 0.95 (elevated); 0.92 clears only the default bar.
        r = decide(raw(("primary_category/LEGAL", 0.92)), DEFAULT)
        assert r.primary_category is PrimaryCategory.OTHER
        assert r.requires_human_review is True

    def test_fraud_suspicion_below_its_elevated_auto_threshold_is_not_selected(self):
        r = decide(raw(("primary_category/FRAUD_SUSPICION", 0.94)), DEFAULT)
        assert r.primary_category is PrimaryCategory.OTHER
        assert r.requires_human_review is True

    def test_legal_above_its_elevated_auto_threshold_is_selected(self):
        r = decide(raw(("primary_category/LEGAL", 0.96)), DEFAULT)
        assert r.primary_category is PrimaryCategory.LEGAL
        assert r.confidence == 0.96
        assert r.band is Band.AUTOMATIC

    def test_legal_below_auto_but_above_floor_cedes_primary_to_default_tier(self):
        r = decide(
            raw(
                ("primary_category/LEGAL", 0.92),
                ("primary_category/CLAIM_NEW", 0.91),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        # LEGAL cleared its (elevated-paired) review floor 0.40 -> stays as secondary.
        assert r.secondary_categories == (PrimaryCategory.LEGAL,)


class TestPairwisePrecedence:
    """Ambiguity precedence applies only inside its own pair — never globally."""

    def test_precedence_does_not_leak_across_unrelated_pairs(self):
        # LEGAL and CLAIM_NEW are NOT an ambiguous pair: the higher score wins.
        r = decide(
            raw(
                ("primary_category/LEGAL", 0.92),
                ("primary_category/CLAIM_NEW", 0.91),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW

    def test_precedence_keeps_higher_score_when_no_pair_applies(self):
        r = decide(
            raw(
                ("primary_category/LEGAL", 0.96),
                ("primary_category/CLAIM_NEW", 0.91),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.LEGAL
        assert r.secondary_categories == (PrimaryCategory.CLAIM_NEW,)

    def test_precedence_overrides_higher_score_within_pair(self):
        # COMPLAINT/LEGAL pair: the versioned rule picks COMPLAINT even when LEGAL
        # scored higher (both clear their own auto thresholds).
        r = decide(
            raw(
                ("primary_category/COMPLAINT", 0.91),
                ("primary_category/LEGAL", 0.96),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.COMPLAINT
        assert r.secondary_categories == (PrimaryCategory.LEGAL,)
        assert r.confidence == 0.91

    def test_precedence_rule_decides_its_own_pair(self):
        # Both clear their own auto thresholds; the versioned pair rule: COMPLAINT wins.
        r = decide(
            raw(
                ("primary_category/COMPLAINT", 0.96),
                ("primary_category/LEGAL", 0.96),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.COMPLAINT
        assert r.secondary_categories == (PrimaryCategory.LEGAL,)


class TestImplications:
    def test_sensitive_personal_data_implies_personal_data(self):
        r = decide(
            raw(
                (
                    "sensitivity/SENSITIVE_PERSONAL_DATA",
                    0.91,
                ),
                ("sensitivity/PERSONAL_DATA", 0.50),
            ),
            DEFAULT,
        )
        assert Sensitivity.SENSITIVE_PERSONAL_DATA in r.sensitivity
        assert Sensitivity.PERSONAL_DATA in r.sensitivity


class TestActions:
    def test_no_action_dropped_when_other_actions_present(self):
        r = decide(
            raw(
                ("action/NO_ACTION", 0.95),
                ("action/URGENT", 0.95),
            ),
            DEFAULT,
        )
        assert list(r.actions) == [Action.URGENT]

    def test_no_action_alone_is_kept(self):
        r = decide(raw(("action/NO_ACTION", 0.95)), DEFAULT)
        assert list(r.actions) == [Action.NO_ACTION]


class TestPriority:
    def test_critical_beats_high(self):
        r = decide(
            raw(("priority/HIGH", 0.95), ("priority/CRITICAL", 0.95)),
            DEFAULT,
        )
        assert r.priority is Priority.CRITICAL

    def test_high_beats_normal(self):
        r = decide(raw(("priority/NORMAL", 0.95), ("priority/HIGH", 0.90)), DEFAULT)
        assert r.priority is Priority.HIGH

    def test_normal_beats_low(self):
        r = decide(raw(("priority/LOW", 0.95), ("priority/NORMAL", 0.90)), DEFAULT)
        assert r.priority is Priority.NORMAL

    def test_low_when_only_low_signal(self):
        r = decide(raw(("priority/LOW", 0.95)), DEFAULT)
        assert r.priority is Priority.LOW


class TestClaimTriple:
    def test_new_claim_versus_claim_documentation(self):
        r = decide(
            raw(
                ("primary_category/CLAIM_DOCUMENTATION", 0.92),
                ("primary_category/CLAIM_NEW", 0.96),
            ),
            DEFAULT,
        )
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        assert r.secondary_categories == (PrimaryCategory.CLAIM_DOCUMENTATION,)


class TestDeterminism:
    def test_identical_input_identical_output(self):
        scores_map = raw(
            ("primary_category/CLAIM_NEW", 0.96),
            ("primary_category/CLAIM_DOCUMENTATION", 0.91),
            ("sensitivity/PERSONAL_DATA", 0.70),
            ("action/REPLY_REQUIRED", 0.95),
            ("priority/HIGH", 0.95),
        )
        r1 = decide(scores_map, DEFAULT)
        r2 = decide(dict(scores_map), DEFAULT)
        assert r1 == r2


class TestVersionAttribution:
    """Task 4.3 — precedence/implication config version is recorded and changes with config."""

    def test_config_version_recorded_in_decision(self):
        r = decide(raw(("primary_category/CLAIM_NEW", 0.96)), DEFAULT)
        assert r.threshold_set_version == DEFAULT.version
        assert r.classifier_version == f"tax-mvp1+qs-v1+eng-jev-1.13+th-{DEFAULT.version[:8]}"

    def test_version_differs_when_rules_config_changes(self):
        import dataclasses

        stricter = dataclasses.replace(
            ThresholdConfig.mvp(),
            default_auto_threshold=0.93,
            version="th-stricter",
        )
        r1 = decide(raw(("primary_category/CLAIM_NEW", 0.92)), DEFAULT)
        r2 = decide(raw(("primary_category/CLAIM_NEW", 0.92)), stricter)
        assert r1.threshold_set_version == "th-mvp"
        assert r2.threshold_set_version == "th-stricter"
        assert r1.threshold_set_version != r2.threshold_set_version
        # Same scores, different config: the decision itself follows the config.
        assert r1.primary_category is PrimaryCategory.CLAIM_NEW
        assert r2.primary_category is PrimaryCategory.OTHER

    def test_implication_is_attributed_to_the_config_version(self):
        r = decide(
            raw(
                ("sensitivity/SENSITIVE_PERSONAL_DATA", 0.91),
                ("sensitivity/PERSONAL_DATA", 0.50),
            ),
            DEFAULT,
        )
        assert Sensitivity.PERSONAL_DATA in r.sensitivity
        assert r.threshold_set_version == DEFAULT.version


class TestDecisionShape:
    def test_full_decision_fields(self):
        r = decide(
            raw(
                ("primary_category/CLAIM_NEW", 0.96),
                ("sensitivity/PERSONAL_DATA", 0.70),
                ("action/REPLY_REQUIRED", 0.95),
                ("priority/HIGH", 0.95),
            ),
            DEFAULT,
        )
        assert r.status == "CLASSIFIED"
        assert r.band is Band.AUTOMATIC
        assert r.requires_human_review is True  # PERSONAL_DATA 0.70 >= 0.65 floor
        assert r.queue_reason == "sensitive_signal"
        assert r.threshold_set_version == DEFAULT.version
        assert r.primary_category is PrimaryCategory.CLAIM_NEW
        assert r.sensitivity == (Sensitivity.PERSONAL_DATA,)
        assert r.actions == (Action.REPLY_REQUIRED,)
        assert r.priority is Priority.HIGH

    def test_failed_scoring_yields_failed_decision(self):
        from email_classifier.domain.models import ScoreError

        r = decide({}, DEFAULT, error=ScoreError("engine down"))
        assert r.status == "FAILED"
        assert r.primary_category is None
        assert r.confidence is None
        assert r.band is None
        assert r.requires_human_review is True
        assert r.queue_reason == "scoring_failed"
        assert r.raw_scores == {}
