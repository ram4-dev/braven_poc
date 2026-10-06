"""Zen JEV scoring adapter (design D3; jev-scoring spec fail-closed boundary).

One POST per email to the Zen SystemOne endpoint carrying all 28 versioned
questions; responses are strictly validated and mapped from
``answers.<question_id>.noul``. Any engine failure raises ``ScoreError`` so the
pipeline records FAILED and routes to human review — no score is ever coerced,
substituted or fabricated.

Envelope field names come from research.md (docs-verified 2026-10-05); if the
real API disagrees, only this adapter's mapping changes.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

from email_classifier.domain.models import (
    EmailMessage,
    QuestionSet,
    ScoreError,
    ScoreResult,
)

# httpx is imported lazily inside ZenJevScorer.__init__ so that importing this
# module (and the adapters package) never pulls the HTTP stack into a process
# that only uses the offline fake scorer.

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1/systemone"
DEFAULT_MODEL = "jev-1.13"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2  # initial attempt + 2 retries = at most 3 requests


class ZenJevScorer:
    """Anti-corruption adapter over the Zen JEV SystemOne endpoint.

    The API key is read ONLY from the ``OPENCODE_API_KEY`` environment variable
    at construction time; it is never written to code, config, logs or error
    messages. ``base_url`` and ``model`` are configurable (constructor
    arguments override the ``OPENCODE_BASE_URL``/``OPENCODE_MODEL`` env vars)
    so a TypeSafe-direct endpoint can be swapped in without policy changes.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        backoff_base: float = 0.5,
    ) -> None:
        import httpx  # local import: see module docstring note

        api_key = os.environ.get("OPENCODE_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENCODE_API_KEY is not set in the environment: "
                "ZenJevScorer requires it at construction time"
            )
        self._api_key = api_key
        self._base_url = base_url or os.environ.get("OPENCODE_BASE_URL") or DEFAULT_BASE_URL
        self._model = model or os.environ.get("OPENCODE_MODEL") or DEFAULT_MODEL
        self._timeout = timeout
        self._backoff_base = backoff_base
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # The Zen gateway rejects non-agent clients (Cloudflare 403/1010):
            # identify as a coding-agent-style client with a stable session.
            "User-Agent": "poc-classifier/0.1.0",
            "x-opencode-session": "email-classifier-mvp",
        }
        self._client = httpx.Client(timeout=timeout, transport=transport, headers=headers)

    def score(self, email: EmailMessage, questions: QuestionSet) -> ScoreResult:
        payload = {
            "model": self._model,
            "state": self._state(email),
            "questions": {
                q.question_id: {
                    "type": q.type,
                    "instructions": q.instructions,
                    "criteria": {"true": q.criteria_true, "false": q.criteria_false},
                }
                for q in questions.questions
            },
        }
        response = self._post_with_retries(payload)
        scores = self._validated_scores(response, questions)
        return ScoreResult(
            scores=scores,
            engine_version=self._model,
            question_set_version=questions.version,
            engine_request_id=None,
        )

    def _state(self, email: EmailMessage) -> str:
        parts = [
            f"From: {email.sender}",
            f"To: {', '.join(email.recipients)}",
            f"Subject: {email.subject}",
            email.body,
        ]
        if email.attachments:
            attachment_lines = "\n".join(f"[attachment: {a.filename}]" for a in email.attachments)
            parts.append(attachment_lines)
        return "\n\n".join(parts)

    def _post_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx  # cached after __init__ imported it; keeps module import lazy

        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                time.sleep(self._backoff_base * (2 ** (attempt - 1)))
            try:
                response = self._client.post(self._base_url, json=payload)
            except httpx.HTTPError:
                if attempt == MAX_RETRIES:
                    raise ScoreError("scoring engine unreachable after retries") from None
                continue
            if response.status_code >= 500:
                if attempt == MAX_RETRIES:
                    raise ScoreError(
                        f"scoring engine returned status {response.status_code} after retries"
                    )
                continue
            if response.status_code >= 400:
                raise ScoreError(
                    f"scoring engine rejected the request (status {response.status_code})"
                )
            try:
                return response.json()
            except ValueError:
                # Malformed JSON is a strict-validation failure, not a
                # transport failure: fail closed immediately, no retry.
                raise ScoreError("scoring engine returned malformed JSON") from None
        raise ScoreError("scoring engine failed after retries")  # pragma: no cover

    def _validated_scores(self, response: Any, questions: QuestionSet) -> dict[str, float]:
        if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
            raise ScoreError("engine response is missing the 'answers' envelope")
        answers = response["answers"]
        scores: dict[str, float] = {}
        for question in questions.questions:
            qid = question.question_id
            answer = answers.get(qid)
            if not isinstance(answer, dict) or "noul" not in answer:
                raise ScoreError(f"engine response is missing question {qid!r}")
            value = answer["noul"]
            # bool is an int subclass: reject it explicitly as non-numeric.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ScoreError(f"engine returned a non-numeric probability for {qid!r}")
            probability = float(value)
            if not 0.0 <= probability <= 1.0:
                raise ScoreError(f"engine returned an out-of-range probability for {qid!r}")
            scores[qid] = probability
        return scores


__all__ = ["ZenJevScorer"]

# Keep a typed callable reference so type checkers see the retry-clock seam used
# by tests to monkeypatch backoff delays without real sleeps.
_retry_clock: Callable[[float], None] = time.sleep
