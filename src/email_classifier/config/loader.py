"""Loaders for versioned configuration files (YAML -> domain objects).

Load-time validation only: a configuration that fails validation is rejected
before any classification runs (classification-rules spec: fail at load).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from email_classifier.domain.models import (
    PRIMARY_CATEGORY_LABELS,
    PRIORITY_LABELS,
    SENSITIVITY_LABELS,
    LabelThreshold,
    ThresholdConfig,
)

_DIMENSION_LABELS = {
    "primary_category": PRIMARY_CATEGORY_LABELS,
    "sensitivity": SENSITIVITY_LABELS,
    "action": [],  # not thresholded in the MVP table; reserved key
    "priority": PRIORITY_LABELS,
}


class ConfigError(Exception):
    """Explicit load-time configuration rejection."""


def _validate_row(dimension: str, label: str, auto: float, floor: float, raw_label: str):
    if dimension not in _DIMENSION_LABELS:
        raise ConfigError(f"unknown dimension {dimension!r} for label {label!r}")
    if label not in _DIMENSION_LABELS[dimension]:
        raise ConfigError(
            f"unknown label {label!r} for dimension {dimension!r} (frozen taxonomy)"
        )
    if floor >= auto:
        raise ConfigError(
            f"review floor {floor} for label {label!r} is not below its auto "
            f"threshold {auto} — classification must not run under this configuration"
        )


def load_thresholds(path: str | Path) -> ThresholdConfig:
    """Load and validate a threshold YAML file into a domain ``ThresholdConfig``.

    The version is the first 8 hex chars of the file's SHA-256, so two configs
    differing in any threshold always yield different versions.
    """
    file_path = Path(path)
    raw = file_path.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {file_path}: {exc}") from exc

    if not isinstance(data, dict) or "default" not in data:
        raise ConfigError("threshold configuration requires a 'default' row")

    default = data["default"]
    default_auto = float(default["auto_threshold"])
    default_floor = float(default["review_floor"])

    elevated: dict[str, LabelThreshold] = {}
    for row in data.get("elevated") or []:
        dimension = str(row["dimension"])
        raw_label = str(row["label"])
        auto = float(row["auto_threshold"])
        floor = float(row.get("review_floor", default_floor))

        # Elevation above the default auto threshold requires a paired review
        # floor strictly below the default review floor, named in the error.
        if auto > default_auto and "review_floor" not in row:
            raise ConfigError(
                f"elevated auto threshold {auto} for label {raw_label!r} has no "
                f"paired review floor below the default {default_floor}"
            )
        _validate_row(dimension, raw_label, auto, floor, raw_label)

        key = f"{dimension}/{raw_label}"
        if key in elevated:
            raise ConfigError(f"duplicate threshold row for {key!r}")
        elevated[key] = LabelThreshold(
            dimension=dimension,
            label=raw_label,
            auto_threshold=auto,
            review_floor=floor,
        )

    version = hashlib.sha256(raw).hexdigest()[:8]
    return ThresholdConfig(
        default_auto_threshold=default_auto,
        default_review_floor=default_floor,
        elevated=elevated,
        version=version,
    )
