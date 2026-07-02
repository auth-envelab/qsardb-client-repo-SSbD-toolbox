"""Neutral local summaries for QsarDB prediction-output tables."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from qsardb_client.schemas import QsarDBPredictionRecord


PredictionInput = pd.DataFrame | Iterable[QsarDBPredictionRecord | dict[str, Any]]
RecordTableInput = pd.DataFrame | Iterable[dict[str, Any]]

REQUIRED_SUMMARY_COLUMNS = (
    "compound_id",
    "handle",
    "model_id",
    "endpoint",
    "model_type",
    "status",
)
ENDPOINT_SUMMARY_COLUMNS = ["endpoint", "model_id", "status", "n"]
MODEL_SUMMARY_COLUMNS = ["handle", "model_id", "endpoint", "model_type", "status", "n"]
COMPOUND_SUMMARY_COLUMNS = ["compound_id", "status", "n"]
ERROR_SUMMARY_COLUMNS = ["handle", "model_id", "endpoint", "model_type", "error", "n"]


class RunSummaryError(Exception):
    """Base exception for run-summary failures."""


def predictions_to_dataframe(predictions: PredictionInput) -> pd.DataFrame:
    """Convert prediction records or dictionaries to a copied DataFrame."""

    if isinstance(predictions, pd.DataFrame):
        return predictions.copy(deep=True)
    if isinstance(predictions, (str, bytes)) or predictions is None:
        raise RunSummaryError("Predictions must be a DataFrame or iterable of records.")

    rows: list[dict[str, Any]] = []
    try:
        iterator = iter(predictions)
    except TypeError as exc:
        raise RunSummaryError("Predictions must be a DataFrame or iterable of records.") from exc

    for item in iterator:
        if isinstance(item, QsarDBPredictionRecord):
            rows.append(item.model_dump(mode="python"))
        elif isinstance(item, dict):
            rows.append(dict(item))
        else:
            raise RunSummaryError(
                "Predictions iterable must contain QsarDBPredictionRecord objects or dictionaries."
            )

    return pd.DataFrame(rows)


def summarize_by_endpoint(predictions: PredictionInput) -> pd.DataFrame:
    """Count prediction statuses by endpoint and model."""

    df = _validated_predictions(predictions)
    return _group_count(df, ["endpoint", "model_id", "status"], ENDPOINT_SUMMARY_COLUMNS)


def summarize_by_model(predictions: PredictionInput) -> pd.DataFrame:
    """Count prediction statuses by QsarDB handle/model/endpoint."""

    df = _validated_predictions(predictions)
    return _group_count(
        df,
        ["handle", "model_id", "endpoint", "model_type", "status"],
        MODEL_SUMMARY_COLUMNS,
    )


def summarize_by_compound(predictions: PredictionInput) -> pd.DataFrame:
    """Count prediction statuses by compound identifier."""

    df = _validated_predictions(predictions)
    return _group_count(df, ["compound_id", "status"], COMPOUND_SUMMARY_COLUMNS)


def summarize_errors(predictions: PredictionInput) -> pd.DataFrame:
    """Count repeated non-ok statuses and explicit error messages."""

    df = _validated_predictions(predictions)
    if "error" in df.columns:
        error_text = df["error"].fillna("").astype(str)
    else:
        error_text = pd.Series([""] * len(df), index=df.index)

    status_text = df["status"].fillna("").astype(str)
    selected = status_text.ne("ok") | error_text.str.strip().ne("")
    error_df = df.loc[selected].copy()
    if error_df.empty:
        return pd.DataFrame(columns=ERROR_SUMMARY_COLUMNS)

    selected_errors = error_text.loc[selected].str.strip()
    error_df["error"] = selected_errors.mask(selected_errors.eq(""), "<no error text>")
    return _group_count(
        error_df,
        ["handle", "model_id", "endpoint", "model_type", "error"],
        ERROR_SUMMARY_COLUMNS,
    )


def create_run_metadata(
    *,
    predictions: PredictionInput,
    models: RecordTableInput | None = None,
    input_compounds: RecordTableInput | None = None,
    input_file: str | Path | None = None,
    models_file: str | Path | None = None,
    predictions_file: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Create JSON-serializable neutral run metadata using dynamic counts."""

    prediction_df = _validated_predictions(predictions)
    input_df = _records_to_dataframe(input_compounds, "input_compounds") if input_compounds is not None else None
    model_df = _records_to_dataframe(models, "models") if models is not None else None

    if input_df is not None:
        _require_columns(input_df, ["compound_id"], "input_compounds")
        number_of_input_substances = int(len(input_df))
        input_substance_count_source = "input_compounds"
        expected_compounds = [str(value) for value in input_df["compound_id"].tolist()]
    else:
        compounds = _unique_strings(prediction_df["compound_id"])
        number_of_input_substances = int(len(compounds))
        input_substance_count_source = "predictions_unique_compound_id"
        expected_compounds = compounds

    if model_df is not None:
        _require_columns(model_df, ["handle", "model_id"], "models")
        number_of_models = int(len(model_df))
        model_count_source = "models"
        expected_models = [
            (str(row.handle), str(row.model_id))
            for row in model_df[["handle", "model_id"]].itertuples(index=False)
        ]
    else:
        model_pairs = prediction_df[["handle", "model_id"]].drop_duplicates()
        expected_models = [
            (str(row.handle), str(row.model_id))
            for row in model_pairs.itertuples(index=False)
        ]
        number_of_models = int(len(expected_models))
        model_count_source = "predictions_unique_handle_model_id"

    expected_prediction_records = int(number_of_input_substances * number_of_models)
    actual_prediction_records = int(len(prediction_df))

    actual_pairs = Counter(
        (str(row.compound_id), str(row.handle), str(row.model_id))
        for row in prediction_df[["compound_id", "handle", "model_id"]].itertuples(index=False)
    )
    expected_pairs = Counter(
        (compound_id, handle, model_id)
        for compound_id in expected_compounds
        for handle, model_id in expected_models
    )
    missing_prediction_records = int(
        sum(max(count - actual_pairs.get(pair, 0), 0) for pair, count in expected_pairs.items())
    )

    status_counts = {
        str(status): int(count)
        for status, count in prediction_df["status"].fillna("").astype(str).value_counts().sort_index().items()
    }
    model_count_in_predictions = int(
        len(prediction_df[["handle", "model_id"]].drop_duplicates())
    )

    metadata = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "input_file": _path_to_str(input_file),
        "models_file": _path_to_str(models_file),
        "predictions_file": _path_to_str(predictions_file),
        "number_of_input_substances": number_of_input_substances,
        "number_of_models": number_of_models,
        "expected_prediction_records": expected_prediction_records,
        "actual_prediction_records": actual_prediction_records,
        "status_counts": status_counts,
        "compound_count_in_predictions": int(prediction_df["compound_id"].nunique(dropna=True)),
        "model_count_in_predictions": model_count_in_predictions,
        "endpoint_count_in_predictions": int(prediction_df["endpoint"].nunique(dropna=True)),
        "all_compound_model_pairs_present": missing_prediction_records == 0,
        "missing_prediction_records": missing_prediction_records,
        "input_substance_count_source": input_substance_count_source,
        "model_count_source": model_count_source,
    }
    return _json_safe(metadata)


def write_run_summary_files(
    *,
    predictions: PredictionInput,
    output_dir: str | Path,
    models: RecordTableInput | None = None,
    input_compounds: RecordTableInput | None = None,
    input_file: str | Path | None = None,
    models_file: str | Path | None = None,
    predictions_file: str | Path | None = None,
) -> dict[str, Path]:
    """Write neutral summary CSV files and run metadata JSON."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    prediction_df = predictions_to_dataframe(predictions)

    paths = {
        "endpoint_status_summary": output_path / "endpoint_status_summary.csv",
        "compound_status_summary": output_path / "compound_status_summary.csv",
        "model_status_summary": output_path / "model_status_summary.csv",
        "model_error_summary": output_path / "model_error_summary.csv",
        "run_metadata": output_path / "run_metadata.json",
    }

    summarize_by_endpoint(prediction_df).to_csv(paths["endpoint_status_summary"], index=False)
    summarize_by_compound(prediction_df).to_csv(paths["compound_status_summary"], index=False)
    summarize_by_model(prediction_df).to_csv(paths["model_status_summary"], index=False)
    summarize_errors(prediction_df).to_csv(paths["model_error_summary"], index=False)

    metadata = create_run_metadata(
        predictions=prediction_df,
        models=models,
        input_compounds=input_compounds,
        input_file=input_file,
        models_file=models_file,
        predictions_file=predictions_file,
    )
    paths["run_metadata"].write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return paths


def _validated_predictions(predictions: PredictionInput) -> pd.DataFrame:
    df = predictions_to_dataframe(predictions)
    _require_columns(df, REQUIRED_SUMMARY_COLUMNS, "predictions")
    return df


def _require_columns(df: pd.DataFrame, columns: Iterable[str], table_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise RunSummaryError(
            f"{table_name} table is missing required column(s): {', '.join(missing)}"
        )


def _group_count(df: pd.DataFrame, group_columns: list[str], output_columns: list[str]) -> pd.DataFrame:
    grouped = df.groupby(group_columns, dropna=False).size().reset_index(name="n")
    grouped = grouped.sort_values(group_columns, kind="stable").reset_index(drop=True)
    return grouped[output_columns]


def _records_to_dataframe(records: RecordTableInput, table_name: str) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        return records.copy(deep=True)
    if isinstance(records, (str, bytes)) or records is None:
        raise RunSummaryError(f"{table_name} must be a DataFrame or iterable of dictionaries.")

    rows: list[dict[str, Any]] = []
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise RunSummaryError(f"{table_name} must be a DataFrame or iterable of dictionaries.") from exc

    for item in iterator:
        if isinstance(item, dict):
            rows.append(dict(item))
        else:
            raise RunSummaryError(f"{table_name} iterable must contain dictionaries.")
    return pd.DataFrame(rows)


def _unique_strings(series: pd.Series) -> list[str]:
    return [str(value) for value in series.drop_duplicates().tolist()]


def _path_to_str(path: str | Path | None) -> str | None:
    return None if path is None else str(path)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
