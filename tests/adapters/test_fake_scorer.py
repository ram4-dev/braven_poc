"""Work unit 7 — deterministic fake scorer (RED tests)."""

import builtins
import json


def make_email():
    from email_classifier.domain.models import Attachment, AttachmentStatus, EmailMessage

    return EmailMessage(
        message_id="em-fake-001",
        sender="client@example.com",
        recipients=["inbox@insurer.com"],
        subject="Reclamo por choque",
        body="Necesito abrir un reclamo por un choque ocurrido ayer.",
        received_at=__import__("datetime").datetime(2026, 10, 5, 14, 32),
        thread_id="th-001",
        attachments=(
            Attachment(
                filename="denuncia.pdf",
                mime="application/pdf",
                extracted_text="Denuncia policial N° 123",
                status=AttachmentStatus.EXTRACTED,
            ),
        ),
    )


def load_question_set():
    from email_classifier.config.loader import load_questions

    return load_questions("src/email_classifier/config/questions.yaml")


class TestReproducibleScores:
    def test_same_email_twice_byte_identical_results(self):
        from email_classifier.adapters.fake_scorer import FakeDeterministicScorer

        scorer = FakeDeterministicScorer()
        email = make_email()
        qs = load_question_set()

        r1 = scorer.score(email, qs)
        r2 = scorer.score(email, qs)
        assert json.dumps(r1.scores, sort_keys=True) == json.dumps(
            r2.scores, sort_keys=True
        )
        assert repr(r1) == repr(r2)

    def test_different_emails_get_different_scores(self):
        from email_classifier.adapters.fake_scorer import FakeDeterministicScorer

        scorer = FakeDeterministicScorer()
        qs = load_question_set()
        e1 = make_email()
        e2 = make_email()
        object.__setattr__(e2, "message_id", "em-fake-002")
        object.__setattr__(e2, "body", "Consulta de cotización para flota.")

        s1 = scorer.score(e1, qs).scores
        s2 = scorer.score(e2, qs).scores
        assert s1 != s2

    def test_no_network_httpx_never_imported(self):
        # Prove the FAKE SCORER never imports httpx when scoring, regardless of
        # what other tests loaded process-wide (e.g. the zen adapter's tests).
        import email_classifier.adapters.fake_scorer as fake_module
        imported = []
        real_import = builtins.__import__

        def spy(name, *args, **kwargs):
            imported.append(name.split(".")[0])
            return real_import(name, *args, **kwargs)

        scorer = fake_module.FakeDeterministicScorer()
        builtins.__import__ = spy
        try:
            scorer.score(make_email(), load_question_set())
        finally:
            builtins.__import__ = real_import
        assert "httpx" not in imported
        # No socket dialing either: the adapter stores no transport/client.
        assert not hasattr(scorer, "_client") and not hasattr(scorer, "client")
        assert fake_module.__name__  # module loaded, nothing network-bound


class TestScoreShape:
    def test_one_probability_per_question_in_unit_range(self):
        from email_classifier.adapters.fake_scorer import FakeDeterministicScorer

        scorer = FakeDeterministicScorer()
        qs = load_question_set()
        result = scorer.score(make_email(), qs)

        assert set(result.scores) == {q.question_id for q in qs.questions}
        for value in result.scores.values():
            assert isinstance(value, float)
            assert 0.0 <= value <= 1.0

    def test_provenance_carries_question_set_version(self):
        from email_classifier.adapters.fake_scorer import FakeDeterministicScorer

        result = FakeDeterministicScorer().score(make_email(), load_question_set())
        assert result.question_set_version == load_question_set().version
        assert result.engine_version


class TestSameRulesPath:
    def test_fake_scores_feed_the_real_rules_engine(self):
        from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
        from email_classifier.domain.models import ThresholdConfig
        from email_classifier.domain.rules import decide

        result = FakeDeterministicScorer().score(make_email(), load_question_set())
        decision = decide(result.scores, ThresholdConfig.mvp(),
                          engine_version=result.engine_version,
                          question_set_version=result.question_set_version)
        assert decision.status == "CLASSIFIED"
        assert decision.raw_scores == result.scores
