"""Human-readable end-to-end demonstration (make demo).

Runs the full corpus through the real pipeline (offline: FakeDeterministicScorer)
into a real SQLite file, then prints every stage as inspectable output:
ingest counts, per-stage counts, queue contents, audit trail of one email,
replay with zero engine calls, and metrics against the dataset ground truth.

This is a demonstration, not a test: exit code is always 0 unless the pipeline
raises. The machine-checked invariants live in tests/e2e/test_corpus_run.py
(make test-e2e).
"""
import json
import pathlib
import tempfile
from dataclasses import replace

from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.config.loader import load_questions, load_thresholds
from email_classifier.pipeline.metrics import EvaluationItem, compute_metrics
from email_classifier.pipeline.pipeline import Pipeline
from email_classifier.pipeline.replay import replay

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "datasets/inbox_mvp_v1.json"
QUESTIONS = ROOT / "src/email_classifier/config/questions.yaml"
THRESHOLDS = ROOT / "src/email_classifier/config/thresholds.yaml"


def rule(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


def main() -> None:
    repo = SqliteRepository(pathlib.Path(tempfile.mkdtemp()) / "demo.db")
    questions = load_questions(str(QUESTIONS))
    thresholds = load_thresholds(str(THRESHOLDS))

    rule("1. INGEST: dataset inbox adapter")
    source = InboxDatasetSource.from_file(str(CORPUS))
    result = source.ingest()
    print(f"dataset file        : {CORPUS.name}")
    print(f"emails in dataset   : {len(source.list_emails())}")
    print(f"ingested (idempotent): {result.ingested_count}")
    print(f"rejected (non-synthetic): {len(result.rejected)}")

    rule("2. SCORE + RULES: pipeline run (1 scoring request per email)")
    pipeline = Pipeline(
        repository=repo,
        source=InboxDatasetSource.from_file(str(CORPUS)),
        engine=FakeDeterministicScorer(),
        thresholds=thresholds,
        questions=questions,
    )
    report = pipeline.run()
    print(f"ingested   : {report.ingested}")
    print(f"classified : {report.classified}")
    print(f"failed     : {report.failed}")
    print(f"queued     : {report.queued}  (zero silent drops: every sensitive")
    print("                    signal at/above its review floor is in the queue)")

    rule("3. STORAGE: append-only SQLite audit trail (first email)")
    first_id = report.email_ids[0]
    stored = repo.get_email(first_id)
    record = repo.get_classification_history(first_id)[-1]
    print(f"message_id        : {stored.message_id}")
    print(f"subject           : {stored.subject}")
    print(f"classifier_version: {record.classifier_version}")
    print(f"band              : {record.band.value if record.band else None}")
    top = sorted(record.raw_scores.items(), key=lambda kv: -kv[1])[:4]
    print("top raw scores    :")
    for qid, score in top:
        print(f"  {qid:<45} {score:.3f}")
    primary = record.primary_category.value if record.primary_category else None
    print(f"primary           : {primary}")
    print(f"sensitivity       : {tuple(s.value for s in record.sensitivity)}")

    rule("4. REVIEW QUEUE: what a human must look at")
    queue = repo.list_review_queue()
    by_reason: dict[str, int] = {}
    for entry in queue:
        by_reason[entry.queue_reason or "?"] = by_reason.get(entry.queue_reason or "?", 0) + 1
    print(f"queue size: {len(queue)}")
    for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<35} {count}")

    rule("5. REPLAY: relabel the whole corpus under new thresholds, ZERO engine calls")
    t2 = replace(
        thresholds,
        default_auto_threshold=0.80,
        default_review_floor=0.55,
        version="th-demo-t2",
    )
    replay_report = replay(
        repository=repo, thresholds=t2, email_ids=list(report.email_ids)
    )
    history = repo.get_classification_history(first_id)
    print(f"rows appended by replay : {replay_report.replayed}")
    print(f"history for first email : {len(history)} records (T1 + T2, append-only)")
    print(f"current threshold set   : {history[-1].threshold_set_version}")
    print(f"raw scores byte-identical: {history[0].raw_scores == history[-1].raw_scores}")
    relabeled = sum(
        1
        for email_id in report.email_ids
        if repo.get_classification_history(email_id)[0].primary_category
        != repo.get_classification_history(email_id)[-1].primary_category
    )
    print(f"primary categories that changed: {relabeled}/{len(report.email_ids)}")

    rule("6. METRICS: accuracy against the dataset's frozen ground truth")
    try:
        dataset = json.loads(CORPUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read corpus at {CORPUS}: {exc}") from exc
    expected = {e["message_id"]: e["expected"] for e in dataset["emails"]}
    items = []
    for email_id, message_id in (
        (r["email_id"], r["message_id"])
        for r in repo._conn.execute(
            "SELECT email_id, message_id FROM emails ORDER BY rowid"
        )
    ):
        rec = repo.get_classification_history(email_id)[-1]
        statuses = tuple(
            r["extraction_status"]
            for r in repo._conn.execute(
                "SELECT extraction_status FROM email_attachments WHERE email_id = ?",
                (email_id,),
            )
        )
        items.append(
            EvaluationItem(
                message_id=message_id,
                status=rec.status,
                primary_category=rec.primary_category.value
                if rec.primary_category is not None
                else None,
                secondary_categories=tuple(c.value for c in rec.secondary_categories),
                sensitivity=tuple(s.value for s in rec.sensitivity),
                requires_human_review=rec.requires_human_review,
                queue_reason=rec.queue_reason,
                received_at=rec.received_at,
                classified_at=rec.classified_at,
                classifier_version=rec.classifier_version,
                engine_version=rec.engine_version,
                question_set_version=rec.question_set_version,
                threshold_set_version=rec.threshold_set_version,
                attachment_statuses=statuses,
            )
        )
    metrics = compute_metrics(items, expected, dataset_version="v1")
    accuracy = metrics["accuracy"]
    print(
        f"accuracy (automated, current config):"
        f" {accuracy['numerator']}/{accuracy['denominator']}"
    )
    print("\nsensitive classes (fail-closed priority):")
    for label, v in metrics["sensitive_classes"].items():
        fn = v["false_negative_rate"]
        print(
            f"  {label:<26} FN rate={fn if fn is not None else 'n/a'}"
            f"  expected={v['expected_count']}"
        )
    print("\nNOTE: FakeDeterministicScorer is hash-random by design — its accuracy")
    print("is NOT a product signal. Run 'make live' to evaluate with real JEV.")

    rule("DEMO COMPLETE — all stages executed against real storage and rules")


if __name__ == "__main__":
    main()
