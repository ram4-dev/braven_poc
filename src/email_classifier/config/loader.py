"""Loaders for versioned configuration files (YAML -> domain objects).

Load-time validation only: a configuration that fails validation is rejected
before any classification runs (classification-rules spec: fail at load).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from email_classifier.domain.models import (
    ACTION_LABELS,
    DEFERRED_CATEGORY_LABELS,
    PRIMARY_CATEGORY_LABELS,
    PRIORITY_LABELS,
    SENSITIVITY_LABELS,
    LabelThreshold,
    Question,
    QuestionSet,
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


_QUESTION_DIMENSIONS = {
    "primary_category": PRIMARY_CATEGORY_LABELS,
    "sensitivity": SENSITIVITY_LABELS,
    "action": ACTION_LABELS,
}


def load_questions(path: str | Path) -> QuestionSet:
    """Load and validate the versioned noul question set.

    The version is the first 8 hex chars of the file's SHA-256, so any wording
    or criteria change bumps the version (jev-scoring: question set versioned)
    while stored classifications keep the version they were produced under.
    """
    file_path = Path(path)
    raw = file_path.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {file_path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ConfigError("question set requires a 'questions' list")

    questions: list[Question] = []
    seen: set[str] = set()
    for entry in data["questions"]:
        qid = str(entry.get("question_id", ""))
        dimension, _, label = qid.partition("/")

        if dimension not in _QUESTION_DIMENSIONS:
            raise ConfigError(
                f"unknown dimension {dimension!r} for question {qid!r}"
            )
        if label in DEFERRED_CATEGORY_LABELS:
            raise ConfigError(
                f"question for deferred category label {label!r} is not allowed "
                "in the MVP question set — deferred labels must never be "
                "requested, accepted or emitted"
            )
        if label not in _QUESTION_DIMENSIONS[dimension]:
            raise ConfigError(
                f"unknown label {label!r} for dimension {dimension!r} "
                "(frozen taxonomy)"
            )
        if qid in seen:
            raise ConfigError(f"duplicate question for {qid!r}")
        seen.add(qid)

        qtype = entry.get("type")
        if qtype != "noul":
            raise ConfigError(
                f"question {qid!r} must have type 'noul' (got {qtype!r})"
            )
        instructions = entry.get("instructions")
        criteria_true = entry.get("criteria_true")
        criteria_false = entry.get("criteria_false")
        if not (
            isinstance(instructions, str) and instructions.strip()
            and isinstance(criteria_true, str) and criteria_true.strip()
            and isinstance(criteria_false, str) and criteria_false.strip()
        ):
            raise ConfigError(
                f"question {qid!r} requires non-empty instructions and "
                "true/false criteria"
            )
        questions.append(
            Question(
                question_id=qid,
                type=qtype,
                instructions=instructions,
                criteria_true=criteria_true,
                criteria_false=criteria_false,
            )
        )

    expected = {
        f"{dim}/{label}"
        for dim, labels in _QUESTION_DIMENSIONS.items()
        for label in labels
    }
    missing = expected - seen
    if missing:
        raise ConfigError(
            f"question set is missing questions for MVP labels: "
            f"{sorted(missing)}"
        )
    extra = seen - expected
    if extra:
        raise ConfigError(
            f"question set contains questions outside the MVP taxonomy: "
            f"{sorted(extra)}"
        )

    version = hashlib.sha256(raw).hexdigest()[:8]
    return QuestionSet(version=version, questions=tuple(questions))


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
