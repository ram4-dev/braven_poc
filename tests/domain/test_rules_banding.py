"""Work unit 3 — banding and review routing (classification-rules + human-review RED tests)."""

from email_classifier.domain.models import (
    ACTION_LABELS,
    PRIMARY_CATEGORY_LABELS,
    PRIORITY_LABELS,
    SENSITIVITY_LABELS,
    Band,
    ThresholdConfig,
)
from email_classifier.domain.rules import (
    REASON_HUMAN_REVIEW_BAND,
    REASON_SCORING_FAILED,
    REASON_SENSITIVE_SIGNAL,
    REASON_UNCERTAIN_BAND,
    resolve_bands,
    review_routing,
)


def scores(*pairs: tuple[str, float]) -> dict[str, float]:
    return dict(pairs)


class TestResolveBandsShape:
    def test_bands_are_keyed_by_dimension_label_pairs(self):
        bands = resolve_bands(scores(("primary_category/CLAIM_NEW", 0.96)), ThresholdConfig.mvp())
        assert bands == {("primary_category", "CLAIM_NEW"): Band.AUTOMATIC}

    def test_band_values_are_never_taxonomy_labels(self):
        all_labels = PRIMARY_CATEGORY_LABELS + SENSITIVITY_LABELS + ACTION_LABELS + PRIORITY_LABELS
        raw = scores(
            ("primary_category/CLAIM_NEW", 0.96),
            ("primary_category/FRAUD_SUSPICION", 0.80),
            ("sensitivity/HIGHLY_CONFIDENTIAL", 0.50),
            ("sensitivity/PERSONAL_DATA", 0.70),
        )
        for band in resolve_bands(raw, ThresholdConfig.mvp()).values():
            assert band in set(Band)
            assert band.value not in all_labels


class TestDefaultBandBoundaries:
    def test_090_is_automatic(self):
        bands = resolve_bands(scores(("primary_category/CLAIM_NEW", 0.90)), ThresholdConfig.mvp())
        assert bands[("primary_category", "CLAIM_NEW")] is Band.AUTOMATIC

    def test_065_is_uncertain(self):
        bands = resolve_bands(scores(("primary_category/CLAIM_NEW", 0.65)), ThresholdConfig.mvp())
        assert bands[("primary_category", "CLAIM_NEW")] is Band.UNCERTAIN

    def test_064_is_human_review(self):
        bands = resolve_bands(scores(("primary_category/CLAIM_NEW", 0.64)), ThresholdConfig.mvp())
        assert bands[("primary_category", "CLAIM_NEW")] is Band.HUMAN_REVIEW


class TestElevatedTier:
    def test_fraud_suspicion_094_is_not_auto_accepted(self):
        bands = resolve_bands(
            scores(("primary_category/FRAUD_SUSPICION", 0.94)), ThresholdConfig.mvp()
        )
        assert bands[("primary_category", "FRAUD_SUSPICION")] is Band.UNCERTAIN

    def test_highly_confidential_uses_elevated_row(self):
        bands = resolve_bands(
            scores(("sensitivity/HIGHLY_CONFIDENTIAL", 0.92)), ThresholdConfig.mvp()
        )
        assert bands[("sensitivity", "HIGHLY_CONFIDENTIAL")] is Band.UNCERTAIN

    def test_non_elevated_personal_data_stays_on_default(self):
        bands = resolve_bands(scores(("sensitivity/PERSONAL_DATA", 0.92)), ThresholdConfig.mvp())
        assert bands[("sensitivity", "PERSONAL_DATA")] is Band.AUTOMATIC


class TestBoundaryMatrix:
    """0.40 / 0.6499 / 0.65 / 0.8999 / 0.90 / 0.9499 / 0.95 for both tiers."""

    BOUNDARY_SCORES = [0.40, 0.6499, 0.65, 0.8999, 0.90, 0.9499, 0.95]

    def test_default_tier_matrix(self):
        expected = {
            0.40: Band.HUMAN_REVIEW,
            0.6499: Band.HUMAN_REVIEW,
            0.65: Band.UNCERTAIN,
            0.8999: Band.UNCERTAIN,
            0.90: Band.AUTOMATIC,
            0.9499: Band.AUTOMATIC,
            0.95: Band.AUTOMATIC,
        }
        for score, band in expected.items():
            bands = resolve_bands(
                scores(("primary_category/CLAIM_NEW", score)), ThresholdConfig.mvp()
            )
            assert bands[("primary_category", "CLAIM_NEW")] is band, f"default tier score {score}"

    def test_elevated_tier_matrix(self):
        expected = {
            0.40: Band.UNCERTAIN,
            0.6499: Band.UNCERTAIN,
            0.65: Band.UNCERTAIN,
            0.8999: Band.UNCERTAIN,
            0.90: Band.UNCERTAIN,
            0.9499: Band.UNCERTAIN,
            0.95: Band.AUTOMATIC,
        }
        for score, band in expected.items():
            bands = resolve_bands(
                scores(("primary_category/FRAUD_SUSPICION", score)),
                ThresholdConfig.mvp(),
            )
            assert bands[("primary_category", "FRAUD_SUSPICION")] is band, (
                f"elevated tier score {score}"
            )


class TestReviewRouting:
    def test_uncertain_band_queued(self):
        routing = review_routing(
            scores(("primary_category/CLAIM_NEW", 0.80)),
            ThresholdConfig.mvp(),
            Band.UNCERTAIN,
        )
        assert routing.requires_human_review is True
        assert routing.queue_reason == REASON_UNCERTAIN_BAND

    def test_human_review_band_queued(self):
        routing = review_routing(
            scores(("primary_category/CLAIM_NEW", 0.50)),
            ThresholdConfig.mvp(),
            Band.HUMAN_REVIEW,
        )
        assert routing.requires_human_review is True
        assert routing.queue_reason == REASON_HUMAN_REVIEW_BAND

    def test_failed_scoring_queued_with_no_fabricated_labels(self):
        routing = review_routing({}, ThresholdConfig.mvp(), None)
        assert routing.requires_human_review is True
        assert routing.queue_reason == REASON_SCORING_FAILED

    def test_no_unfounded_queue_entries(self):
        raw = scores(("primary_category/CLAIM_NEW", 0.96))
        bands = resolve_bands(raw, ThresholdConfig.mvp())
        band = bands[("primary_category", "CLAIM_NEW")]
        routing = review_routing(raw, ThresholdConfig.mvp(), band)
        assert routing.requires_human_review is False
        assert routing.queue_reason is None

    def test_paired_floor_routes_mid_score_sensitive_signal(self):
        raw = scores(("primary_category/FRAUD_SUSPICION", 0.80))
        bands = resolve_bands(raw, ThresholdConfig.mvp())
        routing = review_routing(raw, ThresholdConfig.mvp(), Band.UNCERTAIN)
        assert bands[("primary_category", "FRAUD_SUSPICION")] is Band.UNCERTAIN
        assert routing.requires_human_review is True
        assert routing.queue_reason == REASON_SENSITIVE_SIGNAL

    def test_sensitive_signal_overrides_automatic_band(self):
        raw = scores(
            ("primary_category/CLAIM_NEW", 0.96),
            ("sensitivity/PERSONAL_DATA", 0.80),
        )
        routing = review_routing(raw, ThresholdConfig.mvp(), Band.AUTOMATIC)
        assert routing.requires_human_review is True
        assert routing.queue_reason == REASON_SENSITIVE_SIGNAL

    def test_sensitive_signal_below_floor_does_not_queue(self):
        raw = scores(
            ("primary_category/CLAIM_NEW", 0.96),
            ("sensitivity/PERSONAL_DATA", 0.30),
        )
        routing = review_routing(raw, ThresholdConfig.mvp(), Band.AUTOMATIC)
        assert routing.requires_human_review is False
        assert routing.queue_reason is None

    def test_zero_silent_drops_invariant(self):
        """N emails carrying a sensitive-tier signal >= its floor => N queue entries."""
        sensitive_emails = [
            scores(("primary_category/FRAUD_SUSPICION", 0.55)),
            scores(("primary_category/LEGAL", 0.41)),
            scores(("sensitivity/HIGHLY_CONFIDENTIAL", 0.44)),
            scores(("sensitivity/PERSONAL_DATA", 0.70)),
            scores(("sensitivity/SENSITIVE_PERSONAL_DATA", 0.66)),
            scores(
                ("primary_category/CLAIM_NEW", 0.96),
                ("sensitivity/PERSONAL_DATA", 0.80),
            ),
        ]
        queued = 0
        for raw in sensitive_emails:
            bands = resolve_bands(raw, ThresholdConfig.mvp())
            primary_band = bands.get(("primary_category", "CLAIM_NEW"), Band.HUMAN_REVIEW)
            routing = review_routing(raw, ThresholdConfig.mvp(), primary_band)
            if routing.requires_human_review:
                queued += 1
                assert routing.queue_reason is not None
        assert queued == len(sensitive_emails)


class TestQueueReasonIsStated:
    def test_every_queue_entry_carries_a_reason_string(self):
        cases = [
            (scores(("primary_category/CLAIM_NEW", 0.80)), Band.UNCERTAIN),
            (scores(("primary_category/CLAIM_NEW", 0.50)), Band.HUMAN_REVIEW),
            ({}, None),
            (
                scores(("sensitivity/PERSONAL_DATA", 0.80)),
                Band.AUTOMATIC,
            ),
        ]
        for raw, band in cases:
            routing = review_routing(raw, ThresholdConfig.mvp(), band)
            assert routing.requires_human_review is True
            assert isinstance(routing.queue_reason, str)
            assert routing.queue_reason != ""
