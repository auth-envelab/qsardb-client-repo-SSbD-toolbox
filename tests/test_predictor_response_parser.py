from __future__ import annotations

from qsardb_client.predictor import parse_prediction_response


def test_parse_numeric_assignment_response() -> None:
    assert parse_prediction_response("mpC = 13.8") == ("mpC", "13.8", 13.8)


def test_parse_classification_assignment_response() -> None:
    assert parse_prediction_response("class = active") == ("class", "active", None)


def test_parse_response_without_assignment() -> None:
    assert parse_prediction_response("predicted value: 42.5 units") == (
        None,
        "predicted value: 42.5 units",
        42.5,
    )


def test_parse_empty_response() -> None:
    assert parse_prediction_response("  \n\t  ") == (None, "", None)


def test_parse_scientific_notation() -> None:
    assert parse_prediction_response("value = 1.2e-3") == ("value", "1.2e-3", 0.0012)
