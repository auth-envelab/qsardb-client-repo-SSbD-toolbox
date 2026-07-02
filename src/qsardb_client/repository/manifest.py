"""Neutral manifests from public repository metadata records."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from qsardb_client.repository.oai import OAIMetadataRecord, OAIPMHError


MANIFEST_COLUMNS = [
    "oai_identifier",
    "datestamp",
    "set_specs",
    "title",
    "creators",
    "date",
    "types",
    "identifiers",
    "doi",
    "handle",
    "urls",
    "possible_archive_urls",
    "possible_qmrf_urls",
    "metadata_prefix",
    "discovery_source",
    "raw_metadata_json",
]

URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
DOI_PATTERN = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s<>'\"]+)", re.IGNORECASE)
HANDLE_URL_PATTERN = re.compile(r"https?://hdl\.handle\.net/([^\s<>'\"]+)", re.IGNORECASE)
HDL_PATTERN = re.compile(r"\bhdl:\s*([^\s<>'\"]+)", re.IGNORECASE)
PLAIN_HANDLE_PATTERN = re.compile(r"\b(?!10\.)(\d{4,6}/[A-Za-z0-9._:-]+)\b")
ARCHIVE_EXTENSIONS = (".qdb", ".zip", ".csv")
QMRF_EXTENSIONS = (".pdf", ".xml")


def records_to_manifest(
    records: Iterable[OAIMetadataRecord | dict[str, Any]],
) -> pd.DataFrame:
    """Convert OAI metadata records into a neutral manifest table."""

    rows = []
    for record in records:
        normalized = _normalize_record(record)
        metadata = normalized["metadata"]
        identifiers = _values_for_keys(metadata, {"identifier"})
        all_values = _flatten_metadata_values(metadata)
        urls = _extract_urls(all_values)
        rows.append(
            {
                "oai_identifier": normalized["identifier"],
                "datestamp": normalized["datestamp"] or "",
                "set_specs": _join_values(normalized["set_specs"]),
                "title": _first_value(_values_for_keys(metadata, {"title"})),
                "creators": _join_values(_values_for_keys(metadata, {"creator", "creators"})),
                "date": _first_value(_values_for_keys(metadata, {"date"})),
                "types": _join_values(_values_for_keys(metadata, {"type", "types"})),
                "identifiers": _join_values(identifiers),
                "doi": _join_values(_extract_dois(identifiers)),
                "handle": _join_values(_extract_handles(identifiers)),
                "urls": _join_values(urls),
                "possible_archive_urls": _join_values(_possible_archive_urls(urls)),
                "possible_qmrf_urls": _join_values(_possible_qmrf_urls(urls)),
                "metadata_prefix": normalized["metadata_prefix"] or "",
                "discovery_source": "oai_pmh",
                "raw_metadata_json": json.dumps(metadata, sort_keys=True),
            }
        )
    return pd.DataFrame(rows, columns=MANIFEST_COLUMNS)


def write_manifest_files(
    manifest: pd.DataFrame,
    output_dir: str | Path,
    *,
    basename: str = "repository_records",
) -> dict[str, Path]:
    """Write a repository metadata manifest as CSV and JSON."""

    if not isinstance(manifest, pd.DataFrame):
        raise OAIPMHError("manifest must be a pandas DataFrame")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    clean_basename = str(basename).strip() or "repository_records"
    csv_path = output_path / f"{clean_basename}.csv"
    json_path = output_path / f"{clean_basename}.json"

    dataframe = manifest.copy()
    for column in MANIFEST_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    dataframe = dataframe[MANIFEST_COLUMNS]
    dataframe.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(dataframe.to_dict("records"), indent=2),
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path}


def classify_manifest_feasibility(manifest: pd.DataFrame) -> dict[str, Any]:
    """Summarize neutral manifest discovery coverage."""

    if not isinstance(manifest, pd.DataFrame):
        raise OAIPMHError("manifest must be a pandas DataFrame")
    dataframe = manifest.copy()
    for column in MANIFEST_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = ""
    return {
        "record_count": int(len(dataframe)),
        "records_with_doi": _non_empty_count(dataframe["doi"]),
        "records_with_handle": _non_empty_count(dataframe["handle"]),
        "records_with_urls": _non_empty_count(dataframe["urls"]),
        "records_with_possible_archive_urls": _non_empty_count(dataframe["possible_archive_urls"]),
        "records_with_possible_qmrf_urls": _non_empty_count(dataframe["possible_qmrf_urls"]),
        "discovery_source": "oai_pmh",
        "limitations": (
            "Counts are based only on explicit public OAI-PMH metadata fields; no links were "
            "crawled, no archives were downloaded, and no scientific interpretation was performed."
        ),
    }


def _normalize_record(record: OAIMetadataRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, OAIMetadataRecord):
        return {
            "identifier": record.identifier,
            "datestamp": record.datestamp,
            "set_specs": record.set_specs,
            "metadata_prefix": record.metadata_prefix,
            "metadata": record.metadata,
            "raw_xml": record.raw_xml,
        }
    if isinstance(record, dict):
        return {
            "identifier": str(record.get("identifier") or ""),
            "datestamp": record.get("datestamp"),
            "set_specs": tuple(str(value) for value in record.get("set_specs", [])),
            "metadata_prefix": record.get("metadata_prefix"),
            "metadata": dict(record.get("metadata") or {}),
            "raw_xml": str(record.get("raw_xml") or ""),
        }
    raise OAIPMHError("records must contain OAIMetadataRecord objects or dictionaries")


def _values_for_keys(metadata: dict[str, Any], keys: set[str]) -> list[str]:
    values = []
    for key, value in metadata.items():
        if key.lower() in keys:
            values.extend(_flatten_value(value))
    return _ordered_unique(values)


def _flatten_metadata_values(metadata: dict[str, Any]) -> list[str]:
    values = []
    for value in metadata.values():
        values.extend(_flatten_value(value))
    return _ordered_unique(values)


def _flatten_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        values = []
        for child_value in value.values():
            values.extend(_flatten_value(child_value))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_flatten_value(item))
        return values
    text = str(value).strip()
    return [text] if text else []


def _extract_dois(identifier_values: list[str]) -> list[str]:
    dois = []
    for value in identifier_values:
        for match in DOI_PATTERN.finditer(value):
            dois.append(_trim_terminal_punctuation(match.group(1)))
    return _ordered_unique(dois)


def _extract_handles(identifier_values: list[str]) -> list[str]:
    handles = []
    for value in identifier_values:
        for match in HANDLE_URL_PATTERN.finditer(value):
            handles.append(_trim_terminal_punctuation(match.group(1)))
        for match in HDL_PATTERN.finditer(value):
            handles.append(_trim_terminal_punctuation(match.group(1)))
        if "doi" not in value.lower():
            for match in PLAIN_HANDLE_PATTERN.finditer(value):
                handles.append(_trim_terminal_punctuation(match.group(1)))
    return _ordered_unique(handles)


def _extract_urls(values: list[str]) -> list[str]:
    urls = []
    for value in values:
        urls.extend(_trim_terminal_punctuation(match.group(0)) for match in URL_PATTERN.finditer(value))
    return _ordered_unique(urls)


def _possible_archive_urls(urls: list[str]) -> list[str]:
    return [
        url
        for url in urls
        if _url_path_for_extension(url).endswith(ARCHIVE_EXTENSIONS)
    ]


def _possible_qmrf_urls(urls: list[str]) -> list[str]:
    result = []
    for url in urls:
        lower_url = url.lower()
        path = _url_path_for_extension(url)
        if "qmrf" in lower_url or path.endswith(QMRF_EXTENSIONS):
            result.append(url)
    return _ordered_unique(result)


def _url_path_for_extension(url: str) -> str:
    return url.lower().split("?", 1)[0].split("#", 1)[0]


def _join_values(values: Iterable[str]) -> str:
    return "; ".join(_ordered_unique(values))


def _first_value(values: Iterable[str]) -> str:
    for value in values:
        if value:
            return value
    return ""


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _trim_terminal_punctuation(value: str) -> str:
    return value.rstrip(".,);]")


def _non_empty_count(series: pd.Series) -> int:
    return int(series.fillna("").map(lambda value: str(value).strip() != "").sum())
