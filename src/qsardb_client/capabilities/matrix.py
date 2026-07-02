"""Neutral model capability matrix construction."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from qsardb_client.schemas import QsarDBModelRecord


class CapabilityMatrixError(Exception):
    """Base exception for model capability matrix failures."""


CAPABILITY_COLUMNS = [
    "handle",
    "model_id",
    "endpoint",
    "model_type",
    "remote_structure_api_available",
    "archive_metadata_available",
    "archive_values_available",
    "descriptor_values_available",
    "property_values_available",
    "prediction_values_available",
    "pmml_present",
    "descriptor_input_possible",
    "local_toolkit_candidate",
    "requires_external_descriptor_software",
    "not_automatable_from_current_public_data",
    "source",
    "evidence",
    "limitations",
]

FLAG_COLUMNS = [
    "remote_structure_api_available",
    "archive_metadata_available",
    "archive_values_available",
    "descriptor_values_available",
    "property_values_available",
    "prediction_values_available",
    "pmml_present",
    "descriptor_input_possible",
    "local_toolkit_candidate",
    "requires_external_descriptor_software",
    "not_automatable_from_current_public_data",
]

SOURCE_VALUES = {"predictor_catalog", "parsed_archive", "merged", "unknown"}


def records_to_dataframe(
    records: pd.DataFrame | Iterable[BaseModel | dict[str, Any]],
) -> pd.DataFrame:
    """Convert local records to a DataFrame without mutating the input."""

    if isinstance(records, pd.DataFrame):
        return records.copy()
    if isinstance(records, (str, bytes)) or not isinstance(records, Iterable):
        raise CapabilityMatrixError("records must be a DataFrame or an iterable of records")

    rows: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, BaseModel):
            rows.append(record.model_dump(mode="json"))
        elif isinstance(record, dict):
            rows.append(dict(record))
        else:
            raise CapabilityMatrixError(
                "records iterable must contain pydantic BaseModel instances or dictionaries"
            )
    return pd.DataFrame(rows)


def build_remote_capability_rows(
    models: pd.DataFrame | Iterable[QsarDBModelRecord | dict[str, Any]],
) -> pd.DataFrame:
    """Build capability rows from already-available predictor catalogue records."""

    dataframe = records_to_dataframe(models)
    if dataframe.empty:
        return _empty_capability_matrix()
    _require_columns(dataframe, ["handle", "model_id"], "predictor catalogue models")
    _require_non_empty_values(dataframe, ["handle", "model_id"], "predictor catalogue models")

    working = dataframe.copy()
    if "endpoint" not in working.columns:
        working["endpoint"] = ""
    if "model_type" not in working.columns:
        working["model_type"] = ""
    working["_cap_handle"] = working["handle"].map(_clean_text)
    working["_cap_model_id"] = working["model_id"].map(_clean_text)

    rows = []
    for (handle, model_id), group in working.groupby(["_cap_handle", "_cap_model_id"], sort=False):
        rows.append(
            {
                "handle": handle,
                "model_id": model_id,
                "endpoint": _first_non_empty(group["endpoint"].tolist()),
                "model_type": _first_non_empty(group["model_type"].tolist()),
                "remote_structure_api_available": True,
                "archive_metadata_available": False,
                "archive_values_available": False,
                "descriptor_values_available": False,
                "property_values_available": False,
                "prediction_values_available": False,
                "pmml_present": False,
                "descriptor_input_possible": False,
                "local_toolkit_candidate": False,
                "requires_external_descriptor_software": False,
                "not_automatable_from_current_public_data": False,
                "source": "predictor_catalog",
                "evidence": "Model appears in the predictor catalogue.",
                "limitations": (
                    "Archive/local capabilities were not evaluated from predictor catalogue "
                    "data alone."
                ),
            }
        )
    return _standardize_capability_table(pd.DataFrame(rows))


def build_archive_capability_rows(
    *,
    handle: str,
    archive_tables: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build conservative capability rows from already-parsed archive tables."""

    clean_handle = _clean_text(handle)
    if not clean_handle:
        raise CapabilityMatrixError("handle is required for archive capability rows")
    if not isinstance(archive_tables, Mapping):
        raise CapabilityMatrixError("archive_tables must be a mapping of table names to DataFrames")

    tables = {
        name: _table_from_mapping(archive_tables, name)
        for name in [
            "xml_files",
            "model_pmml_files",
            "property_values",
            "descriptor_values",
            "prediction_values",
        ]
    }
    xml_model_ids = _model_ids_from_xml_files(tables["xml_files"])
    pmml_model_ids = _model_ids_from_table(tables["model_pmml_files"])
    model_ids = _ordered_unique([*xml_model_ids, *pmml_model_ids])
    if not model_ids:
        return _empty_capability_matrix()

    property_values_available = not tables["property_values"].empty
    descriptor_values_available = not tables["descriptor_values"].empty
    prediction_values_available = not tables["prediction_values"].empty
    archive_values_available = (
        property_values_available
        or descriptor_values_available
        or prediction_values_available
    )

    rows = []
    for model_id in model_ids:
        archive_metadata_available = model_id in set(xml_model_ids)
        pmml_present = model_id in set(pmml_model_ids)
        descriptor_input_possible = _explicit_bool_for_model(
            tables,
            model_id,
            "descriptor_input_possible",
        )
        requires_external_descriptor_software = _explicit_bool_for_model(
            tables,
            model_id,
            "requires_external_descriptor_software",
        )
        supported_evidence_available = any(
            [
                archive_metadata_available,
                archive_values_available,
                pmml_present,
                descriptor_input_possible,
            ]
        )
        rows.append(
            {
                "handle": clean_handle,
                "model_id": model_id,
                "endpoint": _lookup_model_value(tables, model_id, "endpoint"),
                "model_type": _lookup_model_value(tables, model_id, "model_type"),
                "remote_structure_api_available": False,
                "archive_metadata_available": archive_metadata_available,
                "archive_values_available": archive_values_available,
                "descriptor_values_available": descriptor_values_available,
                "property_values_available": property_values_available,
                "prediction_values_available": prediction_values_available,
                "pmml_present": pmml_present,
                "descriptor_input_possible": descriptor_input_possible,
                "local_toolkit_candidate": archive_metadata_available or pmml_present,
                "requires_external_descriptor_software": requires_external_descriptor_software,
                "not_automatable_from_current_public_data": not supported_evidence_available,
                "source": "parsed_archive",
                "evidence": _archive_evidence_text(
                    archive_metadata_available=archive_metadata_available,
                    archive_values_available=archive_values_available,
                    descriptor_values_available=descriptor_values_available,
                    property_values_available=property_values_available,
                    prediction_values_available=prediction_values_available,
                    pmml_present=pmml_present,
                ),
                "limitations": (
                    "No model evaluation, descriptor calculation, QMRF parsing, "
                    "applicability-domain analysis, or prediction execution was performed."
                ),
            }
        )
    return _standardize_capability_table(pd.DataFrame(rows))


def merge_capability_rows(
    *capability_tables: pd.DataFrame,
) -> pd.DataFrame:
    """Merge capability rows by QsarDB model identity."""

    if not capability_tables:
        return _empty_capability_matrix()

    standardized_tables = []
    for table in capability_tables:
        if not isinstance(table, pd.DataFrame):
            raise CapabilityMatrixError("capability tables must be pandas DataFrames")
        standardized_tables.append(_standardize_capability_table(table))

    if not standardized_tables:
        return _empty_capability_matrix()

    combined = pd.concat(standardized_tables, ignore_index=True)
    if combined.empty:
        return _empty_capability_matrix()
    _require_columns(combined, ["handle", "model_id"], "capability rows")
    _require_non_empty_values(combined, ["handle", "model_id"], "capability rows")

    rows = []
    for (handle, model_id), group in combined.groupby(["handle", "model_id"], sort=False):
        source_values = _ordered_unique(
            [_clean_source(value) for value in group["source"].tolist()]
        )
        non_unknown_sources = [source for source in source_values if source != "unknown"]
        if len(non_unknown_sources) > 1:
            source = "merged"
        elif non_unknown_sources:
            source = non_unknown_sources[0]
        else:
            source = "unknown"

        row = {
            "handle": handle,
            "model_id": model_id,
            "endpoint": _first_non_empty(group["endpoint"].tolist()),
            "model_type": _first_non_empty(group["model_type"].tolist()),
            "source": source,
            "evidence": _combine_text_values(group["evidence"].tolist()),
            "limitations": _combine_text_values(group["limitations"].tolist()),
        }
        for flag in FLAG_COLUMNS:
            row[flag] = any(_coerce_bool(value) for value in group[flag].tolist())
        rows.append(row)

    result = _standardize_capability_table(pd.DataFrame(rows))
    return result.sort_values(["handle", "model_id"], kind="mergesort").reset_index(drop=True)


def build_model_capability_matrix(
    *,
    predictor_models: pd.DataFrame | Iterable[QsarDBModelRecord | dict[str, Any]] | None = None,
    archive_capabilities: Iterable[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build a merged model capability matrix from local capability evidence."""

    capability_tables = []
    if predictor_models is not None:
        capability_tables.append(build_remote_capability_rows(predictor_models))
    if archive_capabilities is not None:
        for table in archive_capabilities:
            if not isinstance(table, pd.DataFrame):
                raise CapabilityMatrixError("archive_capabilities must contain DataFrames")
            capability_tables.append(table.copy())
    if not capability_tables:
        return _empty_capability_matrix()
    return merge_capability_rows(*capability_tables)


def write_capability_matrix_files(
    matrix: pd.DataFrame,
    output_dir: str | Path,
    *,
    basename: str = "model_capability_matrix",
) -> dict[str, Path]:
    """Write the neutral capability matrix as CSV and JSON files."""

    if not isinstance(matrix, pd.DataFrame):
        raise CapabilityMatrixError("matrix must be a pandas DataFrame")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    clean_basename = _clean_text(basename) or "model_capability_matrix"
    csv_path = output_path / f"{clean_basename}.csv"
    json_path = output_path / f"{clean_basename}.json"

    standardized = _standardize_capability_table(matrix)
    standardized.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(standardized.to_dict("records"), indent=2),
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path}


def _empty_capability_matrix() -> pd.DataFrame:
    return pd.DataFrame(columns=CAPABILITY_COLUMNS)


def _standardize_capability_table(table: pd.DataFrame) -> pd.DataFrame:
    dataframe = table.copy()
    if dataframe.empty:
        return _empty_capability_matrix()
    _require_columns(dataframe, ["handle", "model_id"], "capability rows")

    for column in CAPABILITY_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = False if column in FLAG_COLUMNS else ""

    for column in ["handle", "model_id", "endpoint", "model_type", "evidence", "limitations"]:
        dataframe[column] = dataframe[column].map(_clean_text)
    for column in FLAG_COLUMNS:
        dataframe[column] = dataframe[column].map(_coerce_bool).astype(object)
    dataframe["source"] = dataframe["source"].map(_clean_source)
    return dataframe[CAPABILITY_COLUMNS].copy()


def _require_columns(dataframe: pd.DataFrame, columns: list[str], context: str) -> None:
    missing = [column for column in columns if column not in dataframe.columns]
    if missing:
        raise CapabilityMatrixError(f"{context} missing required columns: {', '.join(missing)}")


def _require_non_empty_values(dataframe: pd.DataFrame, columns: list[str], context: str) -> None:
    for column in columns:
        if dataframe[column].map(_is_blank).any():
            raise CapabilityMatrixError(f"{context} contains empty {column} values")


def _table_from_mapping(tables: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    table = tables.get(name)
    if table is None:
        return pd.DataFrame()
    if not isinstance(table, pd.DataFrame):
        raise CapabilityMatrixError(f"archive table {name} must be a pandas DataFrame")
    return table.copy()


def _model_ids_from_xml_files(xml_files: pd.DataFrame) -> list[str]:
    if xml_files.empty or "container" not in xml_files.columns or "item_id" not in xml_files.columns:
        return []
    model_rows = xml_files[xml_files["container"].map(_clean_text).eq("models")]
    return _ordered_unique([_clean_text(value) for value in model_rows["item_id"].tolist()])


def _model_ids_from_table(table: pd.DataFrame) -> list[str]:
    if table.empty or "item_id" not in table.columns:
        return []
    return _ordered_unique([_clean_text(value) for value in table["item_id"].tolist()])


def _lookup_model_value(
    tables: Mapping[str, pd.DataFrame],
    model_id: str,
    column: str,
) -> str:
    for table_name in ["xml_files", "model_pmml_files"]:
        table = tables[table_name]
        if table.empty or "item_id" not in table.columns or column not in table.columns:
            continue
        matching = table[table["item_id"].map(_clean_text).eq(model_id)]
        value = _first_non_empty(matching[column].tolist())
        if value:
            return value
    return ""


def _explicit_bool_for_model(
    tables: Mapping[str, pd.DataFrame],
    model_id: str,
    column: str,
) -> bool:
    for table_name in ["xml_files", "model_pmml_files"]:
        table = tables[table_name]
        if table.empty or "item_id" not in table.columns or column not in table.columns:
            continue
        matching = table[table["item_id"].map(_clean_text).eq(model_id)]
        for value in matching[column].tolist():
            if not _is_blank(value):
                return _coerce_bool(value)
    return False


def _archive_evidence_text(
    *,
    archive_metadata_available: bool,
    archive_values_available: bool,
    descriptor_values_available: bool,
    property_values_available: bool,
    prediction_values_available: bool,
    pmml_present: bool,
) -> str:
    evidence = []
    if archive_metadata_available:
        evidence.append("model XML metadata in xml_files")
    if pmml_present:
        evidence.append("model PMML cargo in model_pmml_files")
    if property_values_available:
        evidence.append("property_values rows present")
    if descriptor_values_available:
        evidence.append("descriptor_values rows present")
    if prediction_values_available:
        evidence.append("prediction_values rows present")
    if archive_values_available and not evidence:
        evidence.append("archive value rows present")
    return "; ".join(evidence)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _combine_text_values(values: Iterable[Any]) -> str:
    combined = []
    seen = set()
    for value in values:
        for part in _clean_text(value).split(";"):
            text = part.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            combined.append(text)
    return "; ".join(combined)


def _first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _clean_source(value: Any) -> str:
    source = _clean_text(value)
    return source if source in SOURCE_VALUES else "unknown"


def _clean_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return True
    return isinstance(value, str) and value.strip() == ""


def _coerce_bool(value: Any) -> bool:
    if _is_blank(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)
