from __future__ import annotations

import json

import pandas as pd

from qsardb_client.repository import (
    OAIMetadataRecord,
    records_to_manifest,
    write_manifest_files,
)


REQUIRED_COLUMNS = [
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

FORBIDDEN_COLUMN_TERMS = {
    "ssbd",
    "hazard",
    "endpoint_weighting",
    "endpoint_weight",
    "regulatory",
    "safe",
    "unsafe",
}


def _record() -> OAIMetadataRecord:
    return OAIMetadataRecord(
        identifier="oai:qsardb:1",
        datestamp="2026-01-01",
        set_specs=("archive", "public"),
        metadata_prefix="oai_dc",
        metadata={
            "title": "Example archive",
            "creator": ["Alice", "Bob"],
            "date": "2026",
            "type": ["Dataset", "Software"],
            "identifier": [
                "https://doi.org/10.1234/example.1",
                "hdl:10967/1",
                "https://example.invalid/files/example.qdb",
                "https://example.invalid/files/example.zip",
                "https://example.invalid/files/table.csv",
                "https://example.invalid/docs/qmrf.pdf",
                "https://example.invalid/docs/report.xml",
            ],
            "description": "A neutral metadata fixture.",
        },
        raw_xml="<record />",
    )


def test_records_to_manifest_accepts_oai_metadata_records() -> None:
    manifest = records_to_manifest([_record()])

    assert len(manifest) == 1
    assert manifest.loc[0, "oai_identifier"] == "oai:qsardb:1"


def test_records_to_manifest_accepts_equivalent_dictionaries() -> None:
    record = _record()
    manifest = records_to_manifest(
        [
            {
                "identifier": record.identifier,
                "datestamp": record.datestamp,
                "set_specs": record.set_specs,
                "metadata_prefix": record.metadata_prefix,
                "metadata": record.metadata,
                "raw_xml": record.raw_xml,
            }
        ]
    )

    assert manifest.loc[0, "title"] == "Example archive"


def test_manifest_includes_all_required_columns() -> None:
    manifest = records_to_manifest([_record()])

    assert list(manifest.columns) == REQUIRED_COLUMNS


def test_manifest_extracts_basic_metadata_fields() -> None:
    manifest = records_to_manifest([_record()])
    row = manifest.iloc[0]

    assert row["title"] == "Example archive"
    assert row["creators"] == "Alice; Bob"
    assert row["date"] == "2026"
    assert row["types"] == "Dataset; Software"
    assert row["set_specs"] == "archive; public"


def test_manifest_extracts_doi_only_when_explicit() -> None:
    manifest = records_to_manifest([_record()])

    assert manifest.loc[0, "doi"] == "10.1234/example.1"

    without_doi = records_to_manifest(
        [
            OAIMetadataRecord(
                identifier="oai:qsardb:2",
                datestamp=None,
                set_specs=(),
                metadata_prefix="oai_dc",
                metadata={"identifier": "hdl:10967/2"},
                raw_xml="<record />",
            )
        ]
    )
    assert without_doi.loc[0, "doi"] == ""


def test_manifest_extracts_handle_only_when_explicit() -> None:
    manifest = records_to_manifest([_record()])

    assert manifest.loc[0, "handle"] == "10967/1"

    without_handle = records_to_manifest(
        [
            OAIMetadataRecord(
                identifier="oai:qsardb:3",
                datestamp=None,
                set_specs=(),
                metadata_prefix="oai_dc",
                metadata={"identifier": "https://doi.org/10.1234/example.3"},
                raw_xml="<record />",
            )
        ]
    )
    assert without_handle.loc[0, "handle"] == ""


def test_manifest_extracts_only_explicit_urls() -> None:
    manifest = records_to_manifest([_record()])
    urls = manifest.loc[0, "urls"]

    assert "https://example.invalid/files/example.qdb" in urls
    assert "https://example.invalid/docs/qmrf.pdf" in urls


def test_possible_archive_urls_include_explicit_archive_file_urls() -> None:
    manifest = records_to_manifest([_record()])
    archive_urls = manifest.loc[0, "possible_archive_urls"]

    assert "https://example.invalid/files/example.qdb" in archive_urls
    assert "https://example.invalid/files/example.zip" in archive_urls
    assert "https://example.invalid/files/table.csv" in archive_urls


def test_possible_archive_urls_do_not_invent_urls_from_handles() -> None:
    manifest = records_to_manifest(
        [
            OAIMetadataRecord(
                identifier="oai:qsardb:4",
                datestamp=None,
                set_specs=(),
                metadata_prefix="oai_dc",
                metadata={"identifier": "hdl:10967/4"},
                raw_xml="<record />",
            )
        ]
    )

    assert manifest.loc[0, "handle"] == "10967/4"
    assert manifest.loc[0, "possible_archive_urls"] == ""


def test_possible_qmrf_urls_include_explicit_document_urls() -> None:
    manifest = records_to_manifest([_record()])
    qmrf_urls = manifest.loc[0, "possible_qmrf_urls"]

    assert "https://example.invalid/docs/qmrf.pdf" in qmrf_urls
    assert "https://example.invalid/docs/report.xml" in qmrf_urls


def test_raw_metadata_json_is_valid_json() -> None:
    manifest = records_to_manifest([_record()])

    assert json.loads(manifest.loc[0, "raw_metadata_json"])["title"] == "Example archive"


def test_write_manifest_files_writes_readable_csv_and_json(tmp_path) -> None:
    manifest = records_to_manifest([_record()])

    paths = write_manifest_files(manifest, tmp_path, basename="repository_records")

    csv_rows = pd.read_csv(paths["csv"])
    json_rows = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert csv_rows.loc[0, "title"] == "Example archive"
    assert json_rows[0]["title"] == "Example archive"


def test_manifest_has_no_ssbd_or_regulatory_fields() -> None:
    manifest = records_to_manifest([_record()])

    lower_columns = {column.lower() for column in manifest.columns}
    for forbidden in FORBIDDEN_COLUMN_TERMS:
        assert all(forbidden not in column for column in lower_columns)
