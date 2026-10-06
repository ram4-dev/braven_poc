"""Deterministic fake scorer (jev-scoring spec: deterministic fake scorer).

Hash-seeded probabilities: identical email content always yields identical
scores, with no network access and no httpx dependency. The fake feeds the
same rules path as the real engine — no test-only decision branch exists.
"""

from __future__ import annotations

import hashlib
from typing import Any

from email_classifier.domain.models import EmailMessage, QuestionSet, ScoreResult

_ENGINE_VERSION = "fake-1"


def _stable_seed(*parts: Any) -> int:
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big")


class FakeDeterministicScorer:
    """Offline scoring engine: one deterministic probability per question."""

    def score(self, email: EmailMessage, questions: QuestionSet) -> ScoreResult:
        scores: dict[str, float] = {}
        for question in questions.questions:
            # Seed from the question plus the full normalized email content so
            # the same email reproduces byte-identical results and different
            # emails diverge. A 48-bit mantissa keeps the value in 0..1.
            seed = _stable_seed(
                question.question_id,
                email.message_id,
                email.subject,
                email.body,
                email.sender,
                tuple(email.recipients),
                email.thread_id,
                tuple(
                    (a.filename, a.mime, a.extracted_text, a.status.value)
                    for a in email.attachments
                ),
            )
            scores[question.question_id] = (seed % (1 << 48)) / (1 << 48)
        return ScoreResult(
            scores=scores,
            engine_version=_ENGINE_VERSION,
            question_set_version=questions.version,
            engine_request_id=None,
        )
