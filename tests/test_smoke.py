"""Smoke test: the package harness must expose a version."""

import email_classifier


def test_package_exposes_version():
    assert hasattr(email_classifier, "__version__")
