"""Work unit 5 — versioned threshold configuration loader (RED tests)."""

from email_classifier.domain.models import ThresholdConfig


def write_yaml(tmp_path, text: str):
    path = tmp_path / "thresholds.yaml"
    path.write_text(text)
    return path


VALID = """\
default:
  auto_threshold: 0.90
  review_floor: 0.65
elevated:
  - dimension: primary_category
    label: FRAUD_SUSPICION
    auto_threshold: 0.95
    review_floor: 0.40
  - dimension: primary_category
    label: LEGAL
    auto_threshold: 0.95
    review_floor: 0.40
  - dimension: sensitivity
    label: HIGHLY_CONFIDENTIAL
    auto_threshold: 0.95
    review_floor: 0.40
"""


class TestLoadValid:
    def test_loads_default_row_plus_three_elevated_rows(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        cfg = load_thresholds(write_yaml(tmp_path, VALID))
        assert isinstance(cfg, ThresholdConfig)
        assert cfg.default_auto_threshold == 0.90
        assert cfg.default_review_floor == 0.65
        assert set(cfg.elevated) == {
            "primary_category/FRAUD_SUSPICION",
            "primary_category/LEGAL",
            "sensitivity/HIGHLY_CONFIDENTIAL",
        }
        assert cfg.elevated["primary_category/LEGAL"].auto_threshold == 0.95
        assert cfg.elevated["primary_category/LEGAL"].review_floor == 0.40

    def test_loads_the_shipped_thresholds_yaml(self):
        from email_classifier.config.loader import load_thresholds

        cfg = load_thresholds("src/email_classifier/config/thresholds.yaml")
        assert set(cfg.elevated) == {
            "primary_category/FRAUD_SUSPICION",
            "primary_category/LEGAL",
            "sensitivity/HIGHLY_CONFIDENTIAL",
        }


class TestLoadTimeValidation:
    def test_floor_at_or_above_auto_rejected(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        bad = VALID.replace("auto_threshold: 0.95", "auto_threshold: 0.35", 1)
        try:
            load_thresholds(write_yaml(tmp_path, bad))
        except Exception as exc:  # explicit load error, no classification runs
            assert "FRAUD_SUSPICION" in str(exc)
        else:
            raise AssertionError("floor >= auto was accepted")

    def test_unknown_label_rejected(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        bad = VALID.replace("FRAUD_SUSPICION", "CLAIM_PAYMENT", 1)
        try:
            load_thresholds(write_yaml(tmp_path, bad))
        except Exception as exc:
            assert "CLAIM_PAYMENT" in str(exc)
        else:
            raise AssertionError("unknown label was accepted")

    def test_unknown_dimension_rejected(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        bad = VALID.replace("dimension: primary_category", "dimension: tone", 1)
        try:
            load_thresholds(write_yaml(tmp_path, bad))
        except Exception as exc:
            assert "tone" in str(exc)
        else:
            raise AssertionError("unknown dimension was accepted")

    def test_elevation_without_paired_lower_floor_rejected_naming_label(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        # LEGAL raised above default but floor left at the default (0.65) —
        # must fail naming LEGAL (elevation requires a strictly lower paired floor).
        bad = (
            "default:\n"
            "  auto_threshold: 0.90\n"
            "  review_floor: 0.65\n"
            "elevated:\n"
            "  - dimension: primary_category\n"
            "    label: LEGAL\n"
            "    auto_threshold: 0.95\n"
        )
        try:
            load_thresholds(write_yaml(tmp_path, bad))
        except Exception as exc:
            assert "LEGAL" in str(exc)
        else:
            raise AssertionError("elevation without paired floor was accepted")


class TestVersioning:
    def test_version_is_sha256_prefix(self, tmp_path):
        import hashlib

        from email_classifier.config.loader import load_thresholds

        path = write_yaml(tmp_path, VALID)
        cfg = load_thresholds(path)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
        assert cfg.version == expected
        assert len(cfg.version) == 8

    def test_differing_configs_yield_different_versions(self, tmp_path):
        from email_classifier.config.loader import load_thresholds

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        cfg1 = load_thresholds(write_yaml(dir_a, VALID))
        cfg2 = load_thresholds(
            write_yaml(dir_b, VALID.replace("review_floor: 0.40", "review_floor: 0.45"))
        )
        assert cfg1.version != cfg2.version
