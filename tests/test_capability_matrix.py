from __future__ import annotations

import json
import socket

import pandas as pd
import pytest

from qsardb_client.capabilities import (
    CapabilityMatrixError,
    build_archive_capability_rows,
    build_model_capability_matrix,
    build_remote_capability_rows,
    merge_capability_rows,
    records_to_dataframe,
    write_capability_matrix_files,
)
from qsardb_client.schemas import QsarDBModelRecord


FORBIDDEN_COLUMN_TERMS = {
    "ssbd",
    "hazard",
    "endpoint_weighting",
    "endpoint_weight",
    "regulatory",
    "safe",
    "unsafe",
}


def test_records_to_dataframe_accepts_dataframe_and_returns_copy() -> None:
    original = pd.DataFrame([{"handle": "10967/1", "model_id": "M1"}])

    result = records_to_dataframe(original)
    result.loc[0, "handle"] = "changed"

    assert result is not original
    assert original.loc[0, "handle"] == "10967/1"


def test_records_to_dataframe_accepts_qsardb_model_records() -> None:
    result = records_to_dataframe(
        [
            QsarDBModelRecord(
                handle="10967/1",
                model_id="M1",
                endpoint="Endpoint",
                model_type="regression",
            )
        ]
    )

    assert result.loc[0, "handle"] == "10967/1"
    assert result.loc[0, "model_id"] == "M1"


def test_records_to_dataframe_accepts_dictionaries() -> None:
    result = records_to_dataframe([{"handle": "10967/1", "model_id": "M1"}])

    assert result.to_dict("records") == [{"handle": "10967/1", "model_id": "M1"}]


def test_records_to_dataframe_raises_for_unsupported_input() -> None:
    with pytest.raises(CapabilityMatrixError):
        records_to_dataframe([object()])


def test_build_remote_capability_rows_deduplicates_and_sets_flags() -> None:
    rows = build_remote_capability_rows(
        [
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "",
                "model_type": "",
            },
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Solubility",
                "model_type": "regression",
            },
            {
                "handle": "10967/2",
                "model_id": "M2",
                "endpoint": "Activity",
                "model_type": "classification",
            },
        ]
    )

    assert len(rows) == 2
    first = rows.iloc[0]
    assert first["handle"] == "10967/1"
    assert first["model_id"] == "M1"
    assert first["endpoint"] == "Solubility"
    assert first["model_type"] == "regression"
    assert first["remote_structure_api_available"] is True
    assert first["archive_metadata_available"] is False
    assert first["descriptor_values_available"] is False
    assert first["local_toolkit_candidate"] is False
    assert first["source"] == "predictor_catalog"


def test_build_remote_capability_rows_requires_handle_and_model_id() -> None:
    with pytest.raises(CapabilityMatrixError):
        build_remote_capability_rows([{"handle": "10967/1"}])

    with pytest.raises(CapabilityMatrixError):
        build_remote_capability_rows([{"handle": "", "model_id": "M1"}])


def test_build_remote_capability_rows_is_count_agnostic() -> None:
    model_count = 137
    rows = build_remote_capability_rows(
        [
            {
                "handle": f"10967/{index}",
                "model_id": f"M{index}",
                "endpoint": f"Endpoint {index}",
                "model_type": "regression",
            }
            for index in range(model_count)
        ]
    )

    assert len(rows) == model_count
    assert "10967/100" in set(rows["handle"])


def _archive_tables() -> dict[str, pd.DataFrame]:
    return {
        "xml_files": pd.DataFrame(
            [
                {
                    "container": "models",
                    "item_id": "M1",
                    "endpoint": "Archive endpoint",
                    "model_type": "regression",
                },
                {"container": "properties", "item_id": "P1"},
            ]
        ),
        "model_pmml_files": pd.DataFrame(
            [
                {"item_id": "M1", "pmml_text": "<PMML />"},
                {"item_id": "M2", "pmml_text": "<PMML />"},
            ]
        ),
        "descriptor_values": pd.DataFrame([{"compound_id": "C1", "value": "0.1"}]),
        "property_values": pd.DataFrame([{"compound_id": "C1", "value": "1.2"}]),
        "prediction_values": pd.DataFrame([{"compound_id": "C1", "value": "active"}]),
    }


def test_build_archive_capability_rows_uses_archive_tables_conservatively() -> None:
    rows = build_archive_capability_rows(
        handle="10967/1",
        archive_tables=_archive_tables(),
    )

    assert rows["model_id"].tolist() == ["M1", "M2"]

    m1 = rows.loc[rows["model_id"].eq("M1")].iloc[0]
    assert m1["endpoint"] == "Archive endpoint"
    assert m1["model_type"] == "regression"
    assert m1["archive_metadata_available"] is True
    assert m1["pmml_present"] is True
    assert m1["descriptor_values_available"] is True
    assert m1["property_values_available"] is True
    assert m1["prediction_values_available"] is True
    assert m1["archive_values_available"] is True
    assert m1["local_toolkit_candidate"] is True
    assert m1["remote_structure_api_available"] is False
    assert m1["descriptor_input_possible"] is False
    assert m1["requires_external_descriptor_software"] is False
    assert m1["source"] == "parsed_archive"
    assert "PMML" in m1["evidence"]
    assert "prediction execution" in m1["limitations"]

    m2 = rows.loc[rows["model_id"].eq("M2")].iloc[0]
    assert m2["archive_metadata_available"] is False
    assert m2["pmml_present"] is True
    assert m2["local_toolkit_candidate"] is True


def test_build_archive_capability_rows_returns_empty_without_model_ids() -> None:
    rows = build_archive_capability_rows(
        handle="10967/1",
        archive_tables={
            "prediction_values": pd.DataFrame(
                [{"item_id": "PR1", "compound_id": "C1", "value": "active"}]
            )
        },
    )

    assert rows.empty
    assert "handle" in rows.columns
    assert "model_id" in rows.columns


def test_build_archive_capability_rows_requires_handle() -> None:
    with pytest.raises(CapabilityMatrixError):
        build_archive_capability_rows(handle="", archive_tables={})


def test_merge_capability_rows_combines_sources_and_sorts() -> None:
    remote = build_remote_capability_rows(
        [
            {
                "handle": "10967/2",
                "model_id": "M2",
                "endpoint": "Second",
                "model_type": "classification",
            },
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Remote endpoint",
                "model_type": "regression",
            },
        ]
    )
    archive = build_archive_capability_rows(
        handle="10967/1",
        archive_tables=_archive_tables(),
    )

    merged = merge_capability_rows(remote, archive)

    assert merged[["handle", "model_id"]].to_dict("records") == [
        {"handle": "10967/1", "model_id": "M1"},
        {"handle": "10967/1", "model_id": "M2"},
        {"handle": "10967/2", "model_id": "M2"},
    ]
    m1 = merged.loc[
        merged["handle"].eq("10967/1") & merged["model_id"].eq("M1")
    ].iloc[0]
    assert m1["remote_structure_api_available"] is True
    assert m1["archive_metadata_available"] is True
    assert m1["pmml_present"] is True
    assert m1["endpoint"] == "Remote endpoint"
    assert m1["model_type"] == "regression"
    assert m1["source"] == "merged"
    assert "predictor catalogue" in m1["evidence"]
    assert "model XML metadata" in m1["evidence"]
    assert "predictor catalogue data alone" in m1["limitations"]
    assert "prediction execution" in m1["limitations"]


def test_merge_capability_rows_returns_empty_standard_matrix_for_no_input() -> None:
    result = merge_capability_rows()

    assert result.empty
    assert "remote_structure_api_available" in result.columns


def test_build_model_capability_matrix_accepts_predictor_models_only() -> None:
    result = build_model_capability_matrix(
        predictor_models=[
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Endpoint",
                "model_type": "regression",
            }
        ]
    )

    assert len(result) == 1
    assert result.loc[0, "remote_structure_api_available"] is True


def test_build_model_capability_matrix_accepts_archive_capabilities_only() -> None:
    archive_rows = build_archive_capability_rows(
        handle="10967/1",
        archive_tables=_archive_tables(),
    )

    result = build_model_capability_matrix(archive_capabilities=[archive_rows])

    assert result["source"].unique().tolist() == ["parsed_archive"]


def test_build_model_capability_matrix_merges_predictor_and_archive_inputs() -> None:
    archive_rows = build_archive_capability_rows(
        handle="10967/1",
        archive_tables=_archive_tables(),
    )

    result = build_model_capability_matrix(
        predictor_models=[
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Endpoint",
                "model_type": "regression",
            }
        ],
        archive_capabilities=[archive_rows],
    )

    m1 = result.loc[result["model_id"].eq("M1")].iloc[0]
    assert m1["source"] == "merged"
    assert m1["remote_structure_api_available"] is True
    assert m1["pmml_present"] is True


def test_build_model_capability_matrix_returns_empty_for_no_inputs() -> None:
    result = build_model_capability_matrix()

    assert result.empty
    assert "source" in result.columns


def test_write_capability_matrix_files_writes_csv_and_json(tmp_path) -> None:
    matrix = build_remote_capability_rows(
        [
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Endpoint",
                "model_type": "regression",
            }
        ]
    )

    paths = write_capability_matrix_files(matrix, tmp_path, basename="capabilities")

    assert set(paths) == {"csv", "json"}
    assert paths["csv"].name == "capabilities.csv"
    assert paths["json"].name == "capabilities.json"

    csv_rows = pd.read_csv(paths["csv"])
    json_rows = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert bool(csv_rows.loc[0, "remote_structure_api_available"]) is True
    assert json_rows[0]["remote_structure_api_available"] is True


def test_capability_matrix_has_no_ssbd_or_regulatory_fields() -> None:
    matrix = build_model_capability_matrix(
        predictor_models=[
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Endpoint",
                "model_type": "regression",
            }
        ]
    )

    lower_columns = {column.lower() for column in matrix.columns}
    for forbidden in FORBIDDEN_COLUMN_TERMS:
        assert all(forbidden not in column for column in lower_columns)


def test_capability_matrix_building_does_not_call_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("network access was attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    matrix = build_model_capability_matrix(
        predictor_models=[
            {
                "handle": "10967/1",
                "model_id": "M1",
                "endpoint": "Endpoint",
                "model_type": "regression",
            }
        ]
    )

    assert len(matrix) == 1
