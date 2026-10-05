"""Pure rules core: banding, selection, implications, precedence, review routing.

Zero I/O, zero engine access. Every threshold comes from the versioned
``ThresholdConfig`` — nothing is hardcoded in decision paths (design D2).
"""

from __future__ import annotations

from dataclasses import dataclass

from email_classifier.domain.models import (
    Action,
    Band,
    Decision,
    PrimaryCategory,
    Priority,
    ScoreError,
    Sensitivity,
    ThresholdConfig,
)

# Queue reasons (human-review spec: each entry states why it was queued).
REASON_SCORING_FAILED = "scoring_failed"
REASON_SENSITIVE_SIGNAL = "sensitive_signal"
REASON_HUMAN_REVIEW_BAND = "human_review_band"
REASON_UNCERTAIN_BAND = "uncertain_band"
REASON_NO_CATEGORY_CLEARED_FLOOR = "no_category_cleared_floor"

# Sensitive-tier labels (classification-rules spec: fail closed, zero silent drops).
SENSITIVE_TIER_LABELS = frozenset(
    {
        "FRAUD_SUSPICION",
        "LEGAL",
        "HIGHLY_CONFIDENTIAL",
        "PERSONAL_DATA",
        "SENSITIVE_PERSONAL_DATA",
    }
)

# Sensitivity implications: versioned with the threshold config (attribution is via
# the recorded config version in every Decision).
SENSITIVITY_IMPLICATIONS: dict[str, frozenset[str]] = {
    "SENSITIVE_PERSONAL_DATA": frozenset({"PERSONAL_DATA"}),
}

# Versioned taxonomy precedence for ambiguous pairs (classification-rules spec:
# COMPLAINT vs LEGAL, claim triple). Earlier entry wins when both clear the floor;
# the loser becomes a secondary category.
AMBIGUITY_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("COMPLAINT", "LEGAL"),
    ("CLAIM_NEW", "CLAIM_DOCUMENTATION"),
    ("CLAIM_NEW", "CLAIM_UPDATE"),
    ("CLAIM_UPDATE", "CLAIM_DOCUMENTATION"),
)


def _parse_key(key: str) -> tuple[str, str]:
    dimension, _, label = key.partition("/")
    if not label:
        raise ScoreError(f"raw score key is not dimension/label: {key!r}")
    return dimension, label


def _threshold_for(thresholds: ThresholdConfig, dimension: str, label: str):
    elevated = thresholds.elevated.get(f"{dimension}/{label}")
    if elevated is not None:
        return elevated.auto_threshold, elevated.review_floor
    return thresholds.default_auto_threshold, thresholds.default_review_floor


def resolve_bands(
    raw_scores: dict[str, float], thresholds: ThresholdConfig
) -> dict[tuple[str, str], Band]:
    """Band every (dimension, label) signal from its own score and threshold row.

    >= auto -> AUTOMATIC; >= review floor and < auto -> UNCERTAIN; < floor -> HUMAN_REVIEW.
    """
    bands: dict[tuple[str, str], Band] = {}
    for key, score in raw_scores.items():
        dimension, label = _parse_key(key)
        auto_threshold, review_floor = _threshold_for(thresholds, dimension, label)
        if score >= auto_threshold:
            band = Band.AUTOMATIC
        elif score >= review_floor:
            band = Band.UNCERTAIN
        else:
            band = Band.HUMAN_REVIEW
        bands[(dimension, label)] = band
    return bands


@dataclass(frozen=True)
class RoutingDecision:
    """Review-routing outcome with the stated queue reason (or None when not queued)."""

    requires_human_review: bool
    queue_reason: str | None


def review_routing(
    raw_scores: dict[str, float],
    thresholds: ThresholdConfig,
    band: Band | None,
) -> RoutingDecision:
    """Route to human review with zero silent drops.

    Order of reasons: failed scoring -> sensitive-tier signal at/above its floor
    (overrides an automatic band) -> HUMAN_REVIEW band -> UNCERTAIN band.
    """
    if band is None:
        return RoutingDecision(True, REASON_SCORING_FAILED)

    for key, score in raw_scores.items():
        dimension, label = _parse_key(key)
        _, review_floor = _threshold_for(thresholds, dimension, label)
        if label in SENSITIVE_TIER_LABELS and score >= review_floor:
            return RoutingDecision(True, REASON_SENSITIVE_SIGNAL)

    if band is Band.HUMAN_REVIEW:
        return RoutingDecision(True, REASON_HUMAN_REVIEW_BAND)
    if band is Band.UNCERTAIN:
        return RoutingDecision(True, REASON_UNCERTAIN_BAND)
    return RoutingDecision(False, None)


_REVIEW_BAND_REASON = {
    Band.HUMAN_REVIEW: REASON_HUMAN_REVIEW_BAND,
    Band.UNCERTAIN: REASON_UNCERTAIN_BAND,
}


def _primary_order(label: str) -> int:
    """Deterministic tie-break: taxonomy declaration order."""
    for index, name in enumerate(PrimaryCategory.__members__):
        if name == label:
            return index
    return len(PrimaryCategory)


def _ambiguity_demoted(floor_cleared: set[str]) -> set[str]:
    """Pairwise ambiguity demotion: within each versioned pair (winner, loser), the
    loser cannot be primary when both cleared their review floors. Never leaks
    across unrelated pairs."""
    demoted: set[str] = set()
    for winner, loser in AMBIGUITY_PRECEDENCE:
        if winner in floor_cleared and loser in floor_cleared:
            demoted.add(loser)
    return demoted


def decide(
    raw_scores: dict[str, float],
    thresholds: ThresholdConfig,
    *,
    engine_version: str = "jev-1.13",
    question_set_version: str = "qs-v1",
    error: ScoreError | None = None,
) -> Decision:
    """Produce the full Decision deterministically from raw scores + config.

    Pure: no I/O, no engine access. Identical (scores, config) -> identical Decision.
    """

    base = dict(
        status="CLASSIFIED",
        classifier_version="tax-mvp1+qs-v1+eng-"
        + engine_version
        + "+th-"
        + thresholds.version[:8],
        engine_version=engine_version,
        question_set_version=question_set_version,
        threshold_set_version=thresholds.version,
        raw_scores=dict(raw_scores),
    )

    if error is not None:
        return Decision(  # fail-closed: no fabricated labels
            status="FAILED",
            classifier_version=base["classifier_version"],
            engine_version=base["engine_version"],
            question_set_version=base["question_set_version"],
            threshold_set_version=thresholds.version,
            raw_scores=dict(raw_scores),
            confidence=None,
            band=None,
            requires_human_review=True,
            primary_category=None,
            secondary_categories=(),
            sensitivity=(),
            actions=(),
            priority=None,
            queue_reason=REASON_SCORING_FAILED,
        )

    bands = resolve_bands(raw_scores, thresholds)

    # --- Primary category selection (per-label eligibility + argmax + tie-break) ---
    category_scores = {
        key.split("/", 1)[1]: score
        for key, score in raw_scores.items()
        if key.startswith("primary_category/")
    }

    def _auto(label: str) -> float:
        return _threshold_for(thresholds, "primary_category", label)[0]

    def _floor(label: str) -> float:
        return _threshold_for(thresholds, "primary_category", label)[1]

    # Each label is primary-eligible only at or above ITS OWN auto threshold
    # (elevated tier raises the bar for FRAUD_SUSPICION/LEGAL).
    primary_eligible = [
        label for label in category_scores if category_scores[label] >= _auto(label)
    ]
    floor_cleared = {
        label for label in category_scores if category_scores[label] >= _floor(label)
    }
    demoted = _ambiguity_demoted(floor_cleared)
    candidates = [label for label in primary_eligible if label not in demoted]
    if candidates:
        # Deterministic tie-break: highest score, then taxonomy declaration order.
        primary_label = min(
            candidates, key=lambda label: (-category_scores[label], _primary_order(label))
        )
        primary = PrimaryCategory[primary_label]
        secondary_pool = floor_cleared - {primary_label}
        secondary = tuple(
            PrimaryCategory[label]
            for label in sorted(
                secondary_pool,
                key=lambda lb: (-category_scores[lb], _primary_order(lb)),
            )
        )
        confidence = category_scores[primary_label]
        band = bands[("primary_category", primary_label)]
    else:
        primary = PrimaryCategory.OTHER
        secondary = ()
        confidence = None
        band = Band.HUMAN_REVIEW

    # --- Sensitivity: labels at/above floor + implications ---
    sensitivity_labels: set[str] = set()
    for key, score in raw_scores.items():
        dimension, label = _parse_key(key)
        if dimension != "sensitivity":
            continue
        _, floor = _threshold_for(thresholds, dimension, label)
        if score >= floor:
            sensitivity_labels.add(label)
            for implied in SENSITIVITY_IMPLICATIONS.get(label, frozenset()):
                sensitivity_labels.add(implied)
    sensitivity = tuple(
        Sensitivity[name]
        for name in Sensitivity.__members__
        if name in sensitivity_labels
    )

    # --- Actions: at/above floor, NO_ACTION exclusivity ---
    action_labels: list[str] = []
    for key, score in raw_scores.items():
        dimension, label = _parse_key(key)
        if dimension != "action":
            continue
        _, floor = _threshold_for(thresholds, dimension, label)
        if score >= floor:
            action_labels.append(label)
    if len(action_labels) > 1 and "NO_ACTION" in action_labels:
        action_labels.remove("NO_ACTION")
    actions = tuple(
        Action[name] for name in Action.__members__ if name in set(action_labels)
    )

    # --- Priority precedence CRITICAL > HIGH > NORMAL > LOW (explicit, versioned) ---
    priority_labels = {
        key.split("/", 1)[1]
        for key, score in raw_scores.items()
        if key.startswith("priority/")
        and score >= thresholds.default_review_floor
    }
    priority = next(
        (
            Priority[label]
            for label in ("CRITICAL", "HIGH", "NORMAL", "LOW")
            if label in priority_labels
        ),
        None,
    )
    if priority is None:
        priority = Priority.NORMAL

    # --- Review routing ---
    routing = review_routing(raw_scores, thresholds, band)
    requires_review = routing.requires_human_review or primary is PrimaryCategory.OTHER
    queue_reason = routing.queue_reason or (
        REASON_NO_CATEGORY_CLEARED_FLOOR if primary is PrimaryCategory.OTHER else None
    )

    return Decision(
        **base,
        confidence=confidence,
        band=band,
        requires_human_review=requires_review,
        primary_category=primary,
        secondary_categories=secondary,
        sensitivity=sensitivity,
        actions=actions,
        priority=priority,
        queue_reason=queue_reason,
    )
