"""Shared input-parsing helpers used by both the CLI and the HTTP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any

import pandas as pd

from qsardb_client.schemas import QsarDBModelRecord


CsvSource = str | Path | IO[bytes] | IO[str]
JsonSource = str | Path | IO[bytes] | IO[str]


def read_compounds_csv(source: CsvSource) -> list[dict[str, str]]:
    """Read a compounds CSV from a path or a file-like object."""

    if isinstance(source, (str, Path)) and not Path(source).is_file():
        raise ValueError(f"input compounds CSV is missing: {source}")

    dataframe = pd.read_csv(source, dtype=str, keep_default_na=False)
    missing_columns = [
        column
        for column in ("compound_id", "input_structure")
        if column not in dataframe.columns
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"compounds CSV is missing required column(s): {missing}")

    return [
        {
            "compound_id": str(row["compound_id"]),
            "input_structure": str(row["input_structure"]),
        }
        for row in dataframe[["compound_id", "input_structure"]].to_dict("records")
    ]


def read_models_json(source: JsonSource) -> list[QsarDBModelRecord]:
    """Read predictor model records from a path or a file-like object."""

    if isinstance(source, (str, Path)) and not Path(source).is_file():
        raise ValueError(f"models JSON is missing: {source}")

    if isinstance(source, (str, Path)):
        with Path(source).open("r", encoding="utf-8") as file_obj:
            payload: Any = json.load(file_obj)
    else:
        payload = json.load(source)

    if not isinstance(payload, list):
        raise ValueError("models JSON must contain a JSON array")

    return [QsarDBModelRecord.model_validate(item) for item in payload]
