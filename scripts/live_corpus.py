"""Live corpus run against real JEV (task 10.6 smoke; parent-owned script).

Reads OPENCODE_API_KEY from .env (gitignored). Run:
    set -a; source .env; set +a; .venv/bin/python scripts/live_corpus.py
"""
import os
import pathlib
import tempfile
import time

from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.adapters.zen_jev import ZenJevScorer
from email_classifier.config.loader import load_questions, load_thresholds
from email_classifier.pipeline.pipeline import Pipeline

ROOT = pathlib.Path(__file__).resolve().parent.parent

_key = None
env_file = ROOT / ".env"
if env_file.exists() and not os.environ.get("OPENCODE_API_KEY"):
    _key = env_file.read_text().strip().split("=", 1)[1]
    os.environ["OPENCODE_API_KEY"] = _key

tmp = pathlib.Path(tempfile.mkdtemp())
repo = SqliteRepository(tmp / "live.sqlite3")
qs = load_questions(str(ROOT / "src/email_classifier/config/questions.yaml"))
th = load_thresholds(str(ROOT / "src/email_classifier/config/thresholds.yaml"))

scorer = ZenJevScorer()
t0 = time.time()
p = Pipeline(
    repository=repo,
    source=InboxDatasetSource.from_file(str(ROOT / "datasets/inbox_mvp_v1.json")),
    engine=scorer,
    thresholds=th,
    questions=qs,
)
rep = p.run()
elapsed = time.time() - t0

print(f"live run: ingested={rep.ingested} classified={rep.classified} "
      f"failed={rep.failed} queued={rep.queued} in {elapsed:.1f}s")

# Persist metrics-relevant artifacts for inspection
import json

data = json.load(open(ROOT / "datasets/inbox_mvp_v1.json"))
expected = {e["message_id"]: e["expected"] for e in data["emails"]}

from email_classifier.pipeline.metrics import EvaluationItem, compute_metrics

items = []
for email_id, message_id in (
    (r["email_id"], r["message_id"])
    for r in repo._conn.execute(
        "SELECT email_id, message_id FROM emails ORDER BY rowid"
    )
):
    history = repo.get_classification_history(email_id)
    record = history[-1]
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
            status=record.status,
            primary_category=record.primary_category.value
            if record.primary_category is not None
            else None,
            secondary_categories=tuple(c.value for c in record.secondary_categories),
            sensitivity=tuple(s.value for s in record.sensitivity),
            requires_human_review=record.requires_human_review,
            queue_reason=record.queue_reason,
            received_at=record.received_at,
            classified_at=record.classified_at,
            classifier_version=record.classifier_version,
            engine_version=record.engine_version,
            question_set_version=record.question_set_version,
            threshold_set_version=record.threshold_set_version,
            attachment_statuses=statuses,
        )
    )

report = compute_metrics(items, expected, dataset_version="v1")
print(f"accuracy: {report['accuracy']['numerator']}/{report['accuracy']['denominator']} "
      f"= {report['accuracy']['share']}")
print("\nsensitive classes:")
for label, v in report["sensitive_classes"].items():
    print(f"  {label}: FN rate={v['false_negative_rate']} TP={v['true_positive_count']} "
          f"expected={v['expected_count']}")
print("\nper-category (top by recall):")
rows = sorted(
    ((k, v) for k, v in report["per_category"].items() if v["expected_count"]),
    key=lambda kv: -(kv[1]["recall"] or 0),
)
for k, v in rows[:8]:
    print(f"  {k}: P={v['precision'] and round(v['precision'], 2)} "
          f"R={v['recall'] and round(v['recall'], 2)} "
          f"(TP={v['true_positive_count']}/{v['expected_count']} pred={v['predicted_count']})")
print("\nreview rate:", report["review_rate"])
print("versions:", report["versions"])
