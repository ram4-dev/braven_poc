# Email Ingestion Specification

## Purpose

Acquire inbound insurance emails from a replaceable source and produce one canonical, idempotently stored representation that every later stage consumes. **Label sets covered:** none (this domain emits no taxonomy labels; label ownership is defined in the `jev-scoring` and `classification-rules` specs).

## Requirements

### Requirement: Replaceable inbox source

The system MUST acquire emails through a single inbox-source boundary, and MUST allow replacing the dataset-backed simulation with another mailbox reader without changing any downstream stage.

#### Scenario: Source replacement leaves the pipeline unchanged

- GIVEN the pipeline runs against the dataset-backed source
- WHEN the source is replaced by a different reader exposing the same boundary
- THEN normalization, scoring, rules, storage, review and metrics stages run unchanged
- AND the stored classification shape does not change

#### Scenario: Empty source

- GIVEN the source returns no emails
- WHEN an ingest run completes
- THEN the run reports zero emails ingested
- AND no error is raised and no classification record is written

### Requirement: Normalized email intake

Each ingested email MUST expose at least: subject, body, sender, recipients, received date, thread identifier, attachment file names, text extracted from attachments, and relevant metadata. The original email MUST be retained together with its classification output.

#### Scenario: Complete email normalized

- GIVEN a source email with subject, body, sender, recipients, date, thread and two attachments
- WHEN the email is ingested
- THEN all listed fields are available to later stages
- AND the original email content remains retrievable alongside its classification

#### Scenario: Missing optional fields

- GIVEN a source email with no thread identifier
- WHEN the email is ingested
- THEN the email is ingested with the thread identifier absent
- AND ingestion does not fail

### Requirement: Idempotent intake

Each distinct message MUST be ingested at most once. Re-running ingestion over the same source MUST NOT duplicate emails and MUST NOT silently reclassify already ingested emails.

#### Scenario: Ingest replayed

- GIVEN an email with message identifier X already ingested
- WHEN the same source is ingested again
- THEN exactly one email record exists for X
- AND no new classification record is produced for X

### Requirement: Attachment extraction with explicit status

Per attachment the system MUST record the file name and an extraction outcome (extracted, not text-extractable, or failed). Text-extractable attachment content MUST be available to scoring. Non-text attachments MUST NOT block ingestion, and their exclusion from scoring MUST be recorded as a documented metrics caveat.

#### Scenario: Text-extractable attachment

- GIVEN an email with a text-extractable document attachment
- WHEN the email is ingested
- THEN its extracted text is available to the scoring stage
- AND the attachment is recorded as extracted

#### Scenario: Image-only attachment

- GIVEN an email whose only attachment is an image
- WHEN the email is ingested
- THEN the email is ingested with that attachment recorded as not text-extractable
- AND the resulting OCR gap is reported as a documented metrics caveat

### Requirement: Synthetic data only

The system MUST process only synthetic email data containing no real personal data.

#### Scenario: Non-synthetic item rejected

- GIVEN a source item identified as real (non-synthetic) content
- WHEN ingestion processes it
- THEN the item is rejected
- AND the rejection is reported, not silently skipped
