"""Tabular and JSON export helpers for QsarDB-native records."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from qsardb_client.schemas import QsarDBEvidenceBundle


RecordLike = BaseModel | dict[str, Any]
_BUNDLE_TABLE_KEYS = [
    "chemicals",
    "archives",
    "models",
    "capabilities",
    "predictions",
    "extracted_tables",
    "raw_files",
]


class ExportError(Exception):
    """Base exception for export utility failures."""


def records_to_dicts(records: Iterable[RecordLike]) -> list[dict[str, Any]]:
    """Convert pydantic records or plain dictionaries to JSON-compatible dicts."""

    converted: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, BaseModel):
            converted.append(record.model_dump(mode="json"))
            continue
        if isinstance(record, dict):
            converted.append(dict(record))
            continue
        raise TypeError(
            "records_to_dicts expects pydantic BaseModel instances or dictionaries; "
            f"got {type(record).__name__}."
        )
    return converted


def records_to_dataframe(records: Iterable[RecordLike]) -> pd.DataFrame:
    """Convert records to a pandas DataFrame without interpretation or scoring."""

    return pd.DataFrame(records_to_dicts(records))


def records_to_csv(
    records: Iterable[RecordLike],
    path: str | Path,
    *,
    index: bool = False,
) -> Path:
    """Write records to CSV and return the path written."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records_to_dataframe(records).to_csv(output_path, index=index)
    return output_path


def records_to_json(
    records: Iterable[RecordLike],
    path: str | Path,
    *,
    indent: int = 2,
) -> Path:
    """Write records as a JSON array and return the path written."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = records_to_dicts(records)
    output_path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    return output_path


def records_to_parquet(
    records: Iterable[RecordLike],
    path: str | Path,
    *,
    index: bool = False,
) -> Path:
    """Write records to Parquet through pandas and return the path written."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = records_to_dataframe(records)
    try:
        dataframe.to_parquet(output_path, index=index)
    except (ImportError, ValueError) as exc:
        raise ExportError(
            "Writing Parquet requires an optional pandas Parquet engine such as "
            "pyarrow or fastparquet. Install one of those engines and retry."
        ) from exc
    return output_path


def evidence_bundle_to_dict(bundle: QsarDBEvidenceBundle) -> dict[str, Any]:
    """Convert a QsarDB evidence bundle to a JSON-compatible dictionary."""

    return bundle.model_dump(mode="json")


def evidence_bundle_to_json(
    bundle: QsarDBEvidenceBundle,
    path: str | Path,
    *,
    indent: int = 2,
) -> Path:
    """Write a full QsarDB evidence bundle JSON object and return the path."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = evidence_bundle_to_dict(bundle)
    output_path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    return output_path


def evidence_bundle_to_tables(bundle: QsarDBEvidenceBundle) -> dict[str, pd.DataFrame]:
    """Convert each evidence bundle section into a named pandas DataFrame."""

    payload = evidence_bundle_to_dict(bundle)
    return {key: records_to_dataframe(payload[key]) for key in _BUNDLE_TABLE_KEYS}