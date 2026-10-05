# Apply Progress: email-classifier-mvp (PR 1 — work units 1–2)

Worktree: `/Users/ramiro/Desktop/projects/braven_poc.pr1-harness-domain`, branch `pr1-harness-domain` (Worktrunk-managed, base f144e01). Delivery: chained stacked-to-main slice, PR 1 of 17. Mode: Strict TDD (`python -m pytest -q`).

## Work Unit 1 — Test Harness

- [x] 1.1 Worktree verified (orchestrator-created Worktrunk worktree `pr1-harness-domain`; `git worktree list` evidence). No new worktree created inside the worktree.
- [x] 1.2 RED: `tests/test_smoke.py` written first. Command: `python3 -m pytest -q` → `ModuleNotFoundError: No module named 'email_classifier'`, `1 error during collection` (verbatim).
- [x] 1.3 GREEN: `pyproject.toml` (PEP 621, src-layout, deps fastapi/httpx/pydantic/PyYAML, dev pytest/pytest-cov/ruff, ruff+pytest config) + `src/email_classifier/__init__.py` with `__version__ = "0.1.0"`. `pip install -e .` into Python 3.12 venv (system python is 3.9; venv via uv at `.venv/`, gitignored). `python -m pytest -q` → `1 passed`. `ruff check .` → `All checks passed!`.
- [x] 1.4 `openspec/config.yaml` testing block verified against landed harness: test/build/lint/coverage commands and `strict_tdd: true` all match. No drift, no edit.

## Work Unit 2 — Domain Contracts and Ports

- [x] 2.1 RED: `tests/domain/test_models.py` (19 tests) + `tests/ports/test_ports.py` (7 tests) written before production code. Command: `.venv/bin/python -m pytest -q tests/domain/test_models.py tests/ports/test_ports.py` → `ModuleNotFoundError: No module named 'email_classifier.domain'`, `2 errors during collection` (verbatim).
- [x] 2.2 GREEN: `src/email_classifier/domain/models.py` — `Band` (exactly AUTOMATIC/UNCERTAIN/HUMAN_REVIEW), `AttachmentStatus`, frozen StrEnum label sets matching `taxonomy_mvp` (16 primary categories, 6 sensitivity, 6 actions, 4 priority; deferred categories absent from enums), frozen `EmailMessage`/`Attachment` (normalized intake, optional `thread_id`), `Question`/`QuestionSet`, `ScoreResult` (+`ScoreError` fail-closed port error), `LabelThreshold`/`ThresholdConfig` (MVP 0.90/0.65 default + 0.95/0.40 elevated for FRAUD_SUSPICION/LEGAL/HIGHLY_CONFIDENTIAL), frozen `Decision` (classified and failed shapes). `src/email_classifier/ports/__init__.py` — runtime-checkable `EmailSource`, `ScoringEngine`, `ClassificationRepository`, `AttachmentExtractor` Protocols.
- [x] 2.3 Verification: `tests/domain/test_import_graph.py` — AST scan proves `domain/` and `ports/` import no adapter/pipeline/api/config modules and no httpx/sqlite3/fastapi/yaml; runtime test proves importing them loads no I/O module. Full suite `28 passed`; focused `python -m pytest -q tests/domain/test_models.py tests/ports/test_ports.py` → `26 passed`; `ruff check .` → `All checks passed!`.

## TDD Cycle Evidence

| Work unit | Task | RED | GREEN | REFACTOR |
|---|---|---|---|---|
| 1 | 1.2/1.3 | `ModuleNotFoundError: No module named 'email_classifier'` (collection error) | `python -m pytest -q` → `1 passed` | N/A — harness minimal |
| 2 | 2.1/2.2 | `ModuleNotFoundError: No module named 'email_classifier.domain'` (2 collection errors) | `26 passed` (models 19 + ports 7) | Ruff UP042 fix: `(str, Enum)` → `(enum.StrEnum)`; suite stayed green (`28 passed`), `ruff check .` clean |
| 2 | 2.3 | Import-graph test ran against already-pure code (verification test, not a RED-first feature test; purity is enforced going forward) | `2 passed` | N/A |

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result (unit 1) | `python -m pytest -q` → 1 passed (exit 0) |
| Runtime harness command and exact result (unit 1) | `python -m pip install -e .` (into venv) → installed successfully; import of `email_classifier.__version__` proven by smoke test |
| Rollback boundary (unit 1) | Delete `pyproject.toml`, `src/email_classifier/`, `tests/test_smoke.py`; revert `.gitignore` `.venv/` line |
| Focused test command and exact result (unit 2) | `python -m pytest -q tests/domain/test_models.py tests/ports/test_ports.py` → 26 passed (exit 0) |
| Runtime harness command (unit 2) | N/A — import-only, zero I/O by design |
| Rollback boundary (unit 2) | Remove `src/email_classifier/domain/`, `src/email_classifier/ports/`, `tests/domain/`, `tests/ports/` |

## Files Changed

| File | Action |
|---|---|
| `pyproject.toml` | Created |
| `.gitignore` | Modified (added `.venv/`) |
| `src/email_classifier/__init__.py` | Created |
| `src/email_classifier/domain/__init__.py` | Created |
| `src/email_classifier/domain/models.py` | Created |
| `src/email_classifier/ports/__init__.py` | Created |
| `tests/test_smoke.py` | Created |
| `tests/domain/test_models.py` | Created |
| `tests/domain/test_import_graph.py` | Created |
| `tests/ports/test_ports.py` | Created |
| `openspec/changes/email-classifier-mvp/tasks.md` | Checkboxes 1.1–1.4, 2.1–2.3 marked |

## Deviations from Design

- Python 3.12 provided by uv-managed venv (`.venv/`, gitignored) because system Python is 3.9; design requires 3.12.
- `ScoreError` lives in `domain/models.py` next to `ScoreResult` (port errors were task-scoped to ports; kept importable from both — ports re-export contract stays engine-neutral).

## Issues Found

- Ruff UP042 flagged `(str, Enum)`; fixed to `(enum.StrEnum)` per Python 3.12 idiom (behavior preserved, all 28 tests pass).

## Remaining Tasks (out of this batch)

- [ ] 3.1 RED `tests/domain/test_rules_banding.py` (Phase 3, work unit 3 — next PR slice)
- [ ] All tasks in Phases 3–10; Phase 11 is parent-owned (review + delivery gates)
