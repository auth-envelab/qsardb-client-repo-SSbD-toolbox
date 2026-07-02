"""Neutral cargo parsing helpers for local QDB archives."""

from __future__ import annotations

import csv
from io import StringIO

import pandas as pd


class CargoParseError(Exception):
    """Base exception for cargo parsing failures."""


def read_text_cargo(data: bytes, *, encoding: str = "utf-8") -> str:
    """Decode cargo bytes as text without interpreting the content."""

    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.rstrip("\r\n")


def parse_two_column_tsv(
    text: str,
    *,
    value_column_name: str,
    source_path: str,
) -> pd.DataFrame:
    """Parse a simple two-column TSV cargo into a neutral table."""

    rows = _read_tsv_rows(text)
    base_columns = ["compound_id", value_column_name, "source_path"]
    if not rows:
        return pd.DataFrame(columns=base_columns)

    has_header = _has_compound_id_header(rows[0])
    if has_header:
        columns = _header_columns(rows[0], value_column_name)
        data_rows = rows[1:]
    else:
        columns = _default_columns(max(len(row) for row in rows), value_column_name)
        data_rows = rows

    records = []
    for row_number, row in enumerate(data_rows, start=2 if has_header else 1):
        if len(row) < 2:
            raise CargoParseError(
                f"Malformed TSV cargo {source_path}: row {row_number} has fewer than 2 columns."
            )
        row_columns = columns
        if len(row) > len(row_columns):
            row_columns = _extend_columns(row_columns, len(row))
        padded = row + [""] * (len(row_columns) - len(row))
        record = dict(zip(row_columns, padded))
        record["source_path"] = source_path
        records.append(record)

    if not records:
        return pd.DataFrame(columns=list(dict.fromkeys(columns + ["source_path"])))
    return pd.DataFrame(records)


def parse_references_tsv(
    text: str,
    *,
    source_path: str,
) -> pd.DataFrame:
    """Parse a references TSV cargo without resolving references."""

    return parse_two_column_tsv(
        text,
        value_column_name="reference_id",
        source_path=source_path,
    )


def make_cargo_error_record(
    *,
    container: str,
    item_id: str,
    cargo_path: str,
    cargo_name: str,
    error: str,
) -> dict[str, str]:
    """Create a JSON-friendly cargo parse error record."""

    return {
        "container": str(container),
        "item_id": str(item_id),
        "cargo_path": str(cargo_path),
        "cargo_name": str(cargo_name),
        "error": str(error),
    }


def _read_tsv_rows(text: str) -> list[list[str]]:
    if text == "" or not text.strip("\r\n"):
        return []
    try:
        reader = csv.reader(StringIO(text), delimiter="\t")
        return [
            row
            for row in reader
            if row and not all(cell == "" for cell in row)
        ]
    except csv.Error as exc:
        raise CargoParseError(f"Malformed TSV cargo: {exc}") from exc


def _has_compound_id_header(row: list[str]) -> bool:
    return bool(row) and row[0].strip().lower() == "compound_id"


def _header_columns(header: list[str], value_column_name: str) -> list[str]:
    columns = []
    seen = set()
    for index, name in enumerate(header):
        if index == 0:
            candidate = "compound_id"
        elif index == 1:
            candidate = name.strip() or value_column_name
        else:
            candidate = name.strip() or f"extra_{index - 1}"
        if candidate in seen:
            candidate = f"{candidate}_{index}"
        seen.add(candidate)
        columns.append(candidate)
    return _extend_columns(columns, 2)


def _default_columns(column_count: int, value_column_name: str) -> list[str]:
    columns = ["compound_id", value_column_name]
    return _extend_columns(columns, column_count)


def _extend_columns(columns: list[str], column_count: int) -> list[str]:
    extended = list(columns)
    while len(extended) < column_count:
        extended.append(f"extra_{len(extended) - 1}")
    return extended
