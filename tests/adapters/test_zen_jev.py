"""Zen JEV adapter tests (jev-scoring spec: one call/email, strict validation, fail-closed).

All engine interaction is simulated with httpx.MockTransport fixtures. The
envelope comes from research.md (docs-verified 2026-10-05):
request  = {"model": "jev-1.13", "state": "<email text>", "questions": {...}}
response = {"answers": {"<question_id>": {"noul": <float 0..1>}}}
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import TYPE_CHECKING

import pytest

from email_classifier.adapters.zen_jev import ZenJevScorer
from email_classifier.config.loader import load_questions
from email_classifier.domain.models import EmailMessage, ScoreError

if TYPE_CHECKING:
    import httpx

QUESTIONS_PATH = "src/email_classifier/config/questions.yaml"
API_KEY = "test-key-not-a-secret"

QUESTIONS = load_questions(QUESTIONS_PATH)
QUESTION_IDS = [q.question_id for q in QUESTIONS.questions]


@pytest.fixture(autouse=True)
def _api_key_env(monkeypatch):
    """Default env key for every test; the missing-key test deletes it."""
    monkeypatch.setenv("OPENCODE_API_KEY", API_KEY)


def _httpx():
    """Lazy httpx access: keeps 'httpx' out of sys.modules at collection time
    so the fake-scorer test (httpx never imported) stays meaningful."""
    import httpx

    return httpx


BASE_URL = "https://opencode.ai/zen/v1/systemone"


def _email() -> EmailMessage:
    from datetime import datetime

    return EmailMessage(
        message_id="m-1",
        sender="client@example.com",
        recipients=["insurer@example.com"],
        subject="New claim for my car policy",
        body="I want to report a new claim for a accident last week.",
        received_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )


def _full_answers() -> dict:
    """A valid engine response: one noul probability per question."""
    return {
        "answers": {
            qid: {"noul": 0.5 + 0.01 * (i % 50)}
            for i, qid in enumerate(QUESTION_IDS)
        }
    }


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return _httpx().Response(
        status_code=status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
        request=_httpx().Request("POST", BASE_URL),
    )


def _scorer(handler, **kwargs) -> ZenJevScorer:
    """Build a scorer over a MockTransport with a zero backoff for fast tests."""
    return ZenJevScorer(
        transport=_httpx().MockTransport(handler),
        backoff_base=0.0,
        **kwargs,
    )


def _recorded_scorer(responses):
    """Scorer over a handler that pops a scripted sequence per request.

    ``responses`` items may be httpx.Response, Exception (raised), or a single
    Exception instance meaning "raise it on every request".
    """
    requests: list[httpx.Request] = []
    if isinstance(responses, Exception):
        scripted = None
        always_raise = responses
    else:
        scripted = list(responses)
        always_raise = None

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if always_raise is not None:
            raise always_raise
        item = scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return _scorer(handler), requests


class TestOneRequestPerEmail:
    def test_exactly_one_post_with_model_and_28_questions(self):
        scorer, requests = _recorded_scorer([_json_response(_full_answers())])

        scorer.score(_email(), QUESTIONS)

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "POST"
        assert str(request.url) == BASE_URL
        body = json.loads(request.content)
        assert body["model"] == "jev-1.13"
        assert set(body["questions"].keys()) == set(QUESTION_IDS)
        assert len(body["questions"]) == 28

    def test_request_carries_type_instructions_criteria_per_question(self):
        scorer, requests = _recorded_scorer([_json_response(_full_answers())])

        scorer.score(_email(), QUESTIONS)

        body = json.loads(requests[0].content)
        for question in QUESTIONS.questions:
            sent = body["questions"][question.question_id]
            assert sent["type"] == question.type
            assert sent["instructions"] == question.instructions
            assert sent["criteria"]["true"] == question.criteria_true
            assert sent["criteria"]["false"] == question.criteria_false

    def test_state_contains_email_content(self):
        scorer, requests = _recorded_scorer([_json_response(_full_answers())])

        scorer.score(_email(), QUESTIONS)

        state = json.loads(requests[0].content)["state"]
        assert "New claim for my car policy" in state
        assert "report a new claim" in state
        assert "client@example.com" in state

    def test_authorization_bearer_from_env_key(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", API_KEY)
        scorer, requests = _recorded_scorer([_json_response(_full_answers())])

        scorer.score(_email(), QUESTIONS)

        assert requests[0].headers["authorization"] == f"Bearer {API_KEY}"


class TestEnvelopeMapping:
    def test_answers_question_id_noul_mapped_verbatim(self):
        payload = _full_answers()
        scorer, _ = _recorded_scorer([_json_response(payload)])

        result = scorer.score(_email(), QUESTIONS)

        for qid in QUESTION_IDS:
            assert result.scores[qid] == payload["answers"][qid]["noul"]
        assert result.engine_version == "jev-1.13"
        assert result.question_set_version == QUESTIONS.version

    def test_engine_vocabulary_does_not_leak_into_labels(self):
        payload = _full_answers()
        # Engine-specific noise in the response must not become internal state.
        payload["answers"]["engine_specific_label"] = {"noul": 0.9}
        scorer, _ = _recorded_scorer([_json_response(payload)])

        result = scorer.score(_email(), QUESTIONS)

        assert set(result.scores.keys()) == set(QUESTION_IDS)
        assert "engine_specific_label" not in result.scores
        assert "jev" not in " ".join(result.scores.keys()).lower()


class TestStrictValidation:
    def test_out_of_range_probability_rejected_no_coercion(self):
        payload = _full_answers()
        payload["answers"][QUESTION_IDS[0]]["noul"] = 1.5
        scorer, _ = _recorded_scorer([_json_response(payload)])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_negative_probability_rejected(self):
        payload = _full_answers()
        payload["answers"][QUESTION_IDS[3]]["noul"] = -0.1
        scorer, _ = _recorded_scorer([_json_response(payload)])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_missing_question_rejected_no_substituted_score(self):
        payload = _full_answers()
        del payload["answers"][QUESTION_IDS[7]]
        scorer, _ = _recorded_scorer([_json_response(payload)])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_non_numeric_value_rejected(self):
        payload = _full_answers()
        payload["answers"][QUESTION_IDS[2]]["noul"] = "high"
        scorer, _ = _recorded_scorer([_json_response(payload)])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_boolean_value_rejected_as_non_numeric(self):
        payload = _full_answers()
        payload["answers"][QUESTION_IDS[2]]["noul"] = True
        scorer, _ = _recorded_scorer([_json_response(payload)])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_malformed_envelope_missing_answers_rejected(self):
        scorer, _ = _recorded_scorer([_json_response({"results": {}})])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)

    def test_malformed_json_rejected(self):
        response = _httpx().Response(
            status_code=200,
            content=b"not json{",
            request=_httpx().Request("POST", BASE_URL),
        )
        scorer, _ = _recorded_scorer([response])

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)


class TestRetryAndFailClosed:
    def test_500_retried_then_success(self):
        scorer, requests = _recorded_scorer(
            [
                _json_response({"error": "boom"}, status_code=500),
                _json_response({"error": "boom"}, status_code=500),
                _json_response(_full_answers()),
            ]
        )

        result = scorer.score(_email(), QUESTIONS)

        assert len(requests) == 3  # initial attempt + max 2 retries
        assert set(result.scores.keys()) == set(QUESTION_IDS)

    def test_500_exhausted_raises_score_error(self):
        scorer, requests = _recorded_scorer(
            [_json_response({"error": "boom"}, status_code=500)] * 3
        )

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)
        assert len(requests) == 3  # never a 4th attempt

    def test_network_error_retried_then_success(self):
        scorer, requests = _recorded_scorer(
            [
                _httpx().ConnectError("connection refused"),
                _json_response(_full_answers()),
            ]
        )

        result = scorer.score(_email(), QUESTIONS)

        assert len(requests) == 2
        assert result.scores[QUESTION_IDS[0]] == _full_answers()["answers"][QUESTION_IDS[0]]["noul"]

    def test_network_error_exhausted_raises_score_error(self):
        scorer, requests = _recorded_scorer(
            _httpx().ConnectError("connection refused")
        )

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)
        assert len(requests) == 3

    def test_4xx_is_not_retried(self):
        scorer, requests = _recorded_scorer(
            [_json_response({"error": "bad request"}, status_code=400)]
        )

        with pytest.raises(ScoreError):
            scorer.score(_email(), QUESTIONS)
        assert len(requests) == 1  # 4xx must never be retried

    def test_exponential_backoff_delays(self, monkeypatch):
        delays: list[float] = []
        monkeypatch.setattr(
            "email_classifier.adapters.zen_jev.time.sleep",
            lambda s: delays.append(s),
        )
        scorer, _ = _recorded_scorer(
            [
                _json_response({"error": "boom"}, status_code=500),
                _json_response({"error": "boom"}, status_code=500),
                _json_response(_full_answers()),
            ]
        )
        slow = ZenJevScorer(
            transport=_httpx().MockTransport(
                lambda request: _json_response(_full_answers())
            ),
            backoff_base=0.25,
        )
        del slow  # delays are asserted on the failing-then-succeeding scorer

        scorer.score(_email(), QUESTIONS)

        assert delays == pytest.approx([0.0, 0.0])  # backoff_base=0 -> 0, 0*2

    def test_exponential_backoff_grows(self, monkeypatch):
        delays: list[float] = []
        monkeypatch.setattr(
            "email_classifier.adapters.zen_jev.time.sleep",
            lambda s: delays.append(s),
        )
        responses = [
            _json_response({"error": "boom"}, status_code=500),
            _json_response({"error": "boom"}, status_code=500),
            _json_response(_full_answers()),
        ]
        scripted = iter(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            return next(scripted)

        scorer = ZenJevScorer(
            transport=_httpx().MockTransport(handler),
            backoff_base=0.25,
        )

        scorer.score(_email(), QUESTIONS)

        assert delays == pytest.approx([0.25, 0.5])


class TestTimeout:
    def test_default_timeout_is_30s(self):
        scorer = _scorer(lambda request: _json_response(_full_answers()))

        scorer.score(_email(), QUESTIONS)

        assert scorer._timeout == 30.0
        assert scorer._client.timeout.connect == 30.0
        assert scorer._client.timeout.read == 30.0


class TestApiKeyHandling:
    def test_missing_env_key_is_a_clear_construction_error(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

        with pytest.raises(ValueError, match="OPENCODE_API_KEY"):
            ZenJevScorer(
                transport=_httpx().MockTransport(
                    lambda request: _json_response(_full_answers())
                )
            )

    def test_api_key_never_logged_or_in_errors(self, monkeypatch, caplog):
        monkeypatch.setenv("OPENCODE_API_KEY", API_KEY)
        caplog.set_level("DEBUG")
        scorer, _ = _recorded_scorer(
            [_json_response({"error": "boom"}, status_code=500)] * 3
        )

        with pytest.raises(ScoreError) as excinfo:
            scorer.score(_email(), QUESTIONS)

        assert API_KEY not in str(excinfo.value)
        assert API_KEY not in caplog.text


class TestConfigurability:
    def test_base_url_and_model_overridable_for_direct_swap(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response(_full_answers())

        scorer = _scorer(
            handler,
            base_url="https://api.typesafe.ai/v1/systemone",
            model="jev-1.13-free",
        )

        result = scorer.score(_email(), QUESTIONS)

        assert str(captured[0].url) == "https://api.typesafe.ai/v1/systemone"
        assert json.loads(captured[0].content)["model"] == "jev-1.13-free"
        assert result.engine_version == "jev-1.13-free"

    def test_base_url_and_model_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_BASE_URL", "https://api.typesafe.ai/v1/systemone")
        monkeypatch.setenv("OPENCODE_MODEL", "jev-1.13-free")
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response(_full_answers())

        scorer = _scorer(handler)

        scorer.score(_email(), QUESTIONS)

        assert str(captured[0].url) == "https://api.typesafe.ai/v1/systemone"
        assert json.loads(captured[0].content)["model"] == "jev-1.13-free"

    def test_constructor_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_MODEL", "jev-1.13-free")
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response(_full_answers())

        scorer = _scorer(handler, model="jev-1.13")

        scorer.score(_email(), QUESTIONS)

        assert json.loads(captured[0].content)["model"] == "jev-1.13"
