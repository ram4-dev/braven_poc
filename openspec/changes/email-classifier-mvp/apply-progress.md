# Apply Progress: email-classifier-mvp (PR 1 — work units 1–2; continued PR 2 — work units 3–5)

Worktree (units 1–2): `/Users/ramiro/Desktop/projects/braven_poc.pr1-harness-domain`, branch `pr1-harness-domain` (Worktrunk-managed, base f144e01). Worktree (units 3–5): `/Users/ramiro/Desktop/projects/braven_poc.pr2-rules-core`, branch `pr2-rules-core`. Delivery: chained stacked-to-main slices, PRs 1→5 of 17. Mode: Strict TDD (`.venv/bin/python -m pytest -q`).

## Work Unit 3 — Banding + Review Routing (PR 2, prior continuation run)

- [x] 3.1 RED `tests/domain/test_rules_banding.py` — 19 tests incl. 7×2 boundary matrix (0.40/0.6499/0.65/0.8999/0.90/0.9499/0.95, default + elevated tiers). RED: `ModuleNotFoundError: No module named 'email_classifier.domain.rules'`.
- [x] 3.2 GREEN `src/email_classifier/domain/rules.py`: `resolve_bands`, `review_routing` (reason precedence: failed → sensitive ≥ floor → HUMAN_REVIEW band → UNCERTAIN band).
- [x] 3.3 Boundary matrix proven; checkboxes 3.1–3.3 marked in tasks.md by the prior run.

## Work Unit 4 — Selection, Implications, Precedence (PR 2, this continuation)

- [x] 4.1/4.3 RED: audited the timed-out run's partial `test_rules_selection.py` (18 tests, complete) + partial `decide()`; added 5 RED tests exposing two real spec defects: (a) selection used the default auto threshold for every label instead of each label's own (LEGAL/FRAUD_SUSPICION at 0.92/0.94 wrongly primary despite 0.95 bar), (b) ambiguity precedence ranked globally, leaking across unrelated pairs (LEGAL outranked CLAIM_NEW though they are not a pair). Plus `TestVersionAttribution` for 4.3 (config version recorded, composite classifier_version, differing configs → differing versions, implication attributed to config). RED run: 4 failed, 25 passed (verbatim: `AssertionError: assert <PrimaryCategory.LEGAL> is <PrimaryCategory.CLAIM_NEW>`).
- [x] 4.2 GREEN: fixed `decide()` — per-label eligibility via `_threshold_for` (auto AND floor), pairwise `_ambiguity_demoted` over `floor_cleared`, argmax with deterministic tie-break (`-score, taxonomy order`); secondary pool = floor-cleared minus primary, score-ordered. No-category-clears-floor → OTHER + review + `no_category_cleared_floor` reason. SENSITIVE_PERSONAL_DATA ⇒ PERSONAL_DATA implication; NO_ACTION exclusivity; priority precedence CRITICAL>HIGH>NORMAL>LOW, default NORMAL. Focused: 29 passed. Full suite: 76 passed.
- [x] 4.3 `TestVersionAttribution` green (see 4.1).

## Work Unit 5 — Thresholds Config + Loader (tasks 5.1–5.2 only; 5.3+ is PR 3)

- [x] 5.1 RED `tests/config/test_thresholds_loader.py` (8 tests): valid table loads (default + 3 elevated rows), shipped YAML loads, floor ≥ auto rejected naming the label, unknown label rejected, unknown dimension rejected, elevation without paired floor rejected naming LEGAL, version = SHA-256 8-char prefix, differing configs → differing versions. RED verbatim: `ModuleNotFoundError: No module named 'email_classifier.config'`, 8 failed.
- [x] 5.2 GREEN `src/email_classifier/config/thresholds.yaml` + `load_thresholds` in `src/email_classifier/config/loader.py` (YAML → domain `ThresholdConfig`; `ConfigError` for all rejections; version = SHA-256(raw file bytes)[:8]). Focused: 8 passed. Runtime harness: `python -c "...load_thresholds('src/email_classifier/config/thresholds.yaml').version"` → `35d4c41e`. Tasks 5.3–5.4 deliberately NOT done (questions.yaml is PR 3).

## TDD Cycle Evidence (units 3–5, this worktree)

| Work unit | Task | RED | GREEN | REFACTOR |
|---|---|---|---|---|
| 3 | 3.1–3.3 | `ModuleNotFoundError: No module named 'email_classifier.domain.rules'` | 19 passed (banding) | Boundary matrix added; suite stayed green |
| 4 | 4.1/4.3 | 4 failed, 25 passed (per-label auto threshold ignored; pairwise precedence leak) | 29 passed (selection file); 76 total | Ruff E741/E501 fixes (`lambda l` → `lambda lb`); suite stayed green |
| 5 | 5.1 | `ModuleNotFoundError: No module named 'email_classifier.config'`, 8 failed | 8 passed; 84 total; ruff clean | Import-graph runtime test pollution fix (purge forbidden roots before import); loader I001 import-sort --fix |

## Work Unit Evidence (units 4–5)

| Evidence | Required value |
|---|---|
| Focused test command and exact result (unit 4) | `.venv/bin/python -m pytest tests/domain/test_rules_selection.py` → 29 passed (exit 0) |
| Runtime harness command and exact result (unit 4) | N/A — pure functions, no I/O by design |
| Rollback boundary (unit 4) | Remove selection/implication/precedence code from `domain/rules.py` + `tests/domain/test_rules_selection.py` (banding code from unit 3 stays) |
| Focused test command and exact result (unit 5) | `.venv/bin/python -m pytest tests/config/test_thresholds_loader.py` → 8 passed (exit 0) |
| Runtime harness command and exact result (unit 5) | `python -c "from email_classifier.config.loader import load_thresholds as l; print(l('src/email_classifier/config/thresholds.yaml').version)"` → `35d4c41e` |
| Rollback boundary (unit 5) | Delete `src/email_classifier/config/` (thresholds.yaml, loader.py, __init__.py) + `tests/config/` |

## Files Changed (this continuation, pr2-rules-core worktree)

| File | Action |
|---|---|
| `src/email_classifier/domain/rules.py` | Created (prior run) + fixed: per-label auto eligibility, pairwise ambiguity demotion, version attribution |
| `tests/domain/test_rules_banding.py` | Created (prior run, 19 tests) |
| `tests/domain/test_rules_selection.py` | Created (prior run) + extended: elevated-auto + pairwise-precedence + version-attribution tests (29 total) |
| `tests/domain/test_import_graph.py` | Modified: runtime purity check purges forbidden root modules before importing (test-pollution fix) |
| `src/email_classifier/config/__init__.py` | Created (empty) |
| `src/email_classifier/config/thresholds.yaml` | Created (default + 3 elevated rows) |
| `src/email_classifier/config/loader.py` | Created (`load_thresholds`, `ConfigError`, SHA-256 version) |
| `tests/config/test_thresholds_loader.py` | Created (8 tests) |
| `openspec/changes/email-classifier-mvp/tasks.md` | Checkboxes 4.1–4.3, 5.1–5.2 marked |

## Deviations from Design

- None for units 4–5. The prior partial `decide()` had two latent spec defects (fixed this run, see 4.1); they were not design deviations, they were implementation bugs caught by RED tests.

## Issues Found

- `test_import_graph.py::test_importing_domain_does_not_load_io_modules` failed once `config/loader.py` legitimately imported `yaml` elsewhere in the session: the runtime check only purged `email_classifier*` from `sys.modules`, so `yaml` loaded by other tests polluted the assertion. Fixed by also purging forbidden root modules before importing domain/ports — the check's intent (domain/ports cause no I/O imports) is unchanged.

## Remaining Tasks (out of this batch)

- [ ] 5.3 RED `tests/config/test_questions_loader.py` (PR 3)
- [ ] 5.4 GREEN `config/questions.yaml` + `load_questions` (PR 3)
- [ ] All tasks in Phases 6–10; Phase 11 is parent-owned (review + delivery gates)

---

## Historical: PR 1 — Work Units 1–2 (pr1-harness-domain worktree)

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
