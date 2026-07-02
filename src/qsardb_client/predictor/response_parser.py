"""Plain-text QsarDB predictor response parsing."""

from __future__ import annotations

import re


_NUMBER_PATTERN = re.compile(
    r"[-+]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][-+]?\d+)?"
)


def _first_float(value: str) -> float | None:
    match = _NUMBER_PATTERN.search(value)
    if match is None:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_prediction_response(text: str) -> tuple[str | None, str | None, float | None]:
    stripped = text.strip()
    if not stripped:
        return None, "", None

    if "=" not in stripped:
        return None, stripped, _first_float(stripped)

    name, value = stripped.split("=", 1)
    result_name = name.strip() or None
    result_value = value.strip()
    return result_name, result_value, _first_float(result_value)
