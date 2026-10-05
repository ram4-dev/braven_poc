# Classification Dashboard Specification

## Purpose

Expose a minimal read view over stored classifications so a human can inspect what was decided for each email, see the evidence behind the decision, and see current values after human review. **Label sets covered:** all MVP dimensions (16 primary categories, 6 sensitivity labels, 6 actions, 4 priorities) plus bands `AUTOMATIC`, `UNCERTAIN`, `HUMAN_REVIEW`.

**Scope boundary:** smart routing, content search across emails, alerting, analytics and workflow automation are explicit non-goals of this change.

## Requirements

### Requirement: Classified email listing

The system MUST expose a listing of classified emails showing, per entry, the primary category, secondary categories, sensitivity, actions, priority, confidence, band, human-review requirement, classifier version and classification timestamp.

#### Scenario: Listing classified emails

- GIVEN 50 classified emails are stored
- WHEN the listing is requested
- THEN each entry exposes the complete stored dimension set and the band
- AND no email present in storage is omitted from the listing

#### Scenario: Unclassified email is visible as unclassified

- GIVEN an email whose scoring failed
- WHEN the listing is requested
- THEN the entry is present and shows the failed status
- AND it shows no invented primary category, sensitivity or confidence

### Requirement: Current values after review

The listing MUST show the current values for an email, meaning reviewer-corrected values where a review exists, while the original automated values remain retrievable.

#### Scenario: Corrected values shown

- GIVEN an email corrected in human review
- WHEN it is viewed
- THEN the corrected values are displayed as current
- AND the original automated values remain retrievable from the same view

#### Scenario: Unreviewed values shown unchanged

- GIVEN an email that was never reviewed
- WHEN it is viewed
- THEN the automated values are displayed as current

### Requirement: Decision evidence is visible

For each classification the view MUST expose the raw scores, the thresholds applied and the composite classifier version, so a decision can be explained without re-running the engine.

#### Scenario: Explaining a stored decision

- GIVEN a stored classification
- WHEN its detail is requested
- THEN the raw scores, the applied thresholds and the composite classifier version are visible
- AND no engine request is issued to produce the explanation

#### Scenario: Explaining a sensitive non-auto label

- GIVEN an email whose sensitive-tier label stayed below its auto threshold and was routed to review
- WHEN its detail is requested
- THEN the label's score, its auto threshold, its review floor and the routing decision are visible
