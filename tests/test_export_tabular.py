from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qsardb_client.export import (
    ExportError,
    evidence_bundle_to_dict,
    evidence_bundle_to_json,
    evidence_bundle_to_tables,
    records_to_csv,
    records_to_dataframe,
    records_to_dicts,
    records_to_json,
    records_to_parquet,
)
from qsardb_client.schemas import (
    ChemicalRecord,
    QsarDBArchiveRecord,
    QsarDBEvidenceBundle,
    QsarDBModelCapability,
    QsarDBModelRecord,
    QsarDBPredictionRecord,
)


BUNDLE_TABLE_KEYS = [
    "chemicals",
    "archives",
    "models",
    "capabilities",
    "predictions",
    "extracted_tables",
    "raw_files",
]


def make_chemical() -> ChemicalRecord:
    return ChemicalRecord(
        compound_id="compound-1",
        input_structure="CCO",
        canonical_smiles="CCO",
        handle="chemical-handle",
    )


def make_bundle() -> QsarDBEvidenceBundle:
    return QsarDBEvidenceBundle(
        chemicals=[make_chemical()],
        archives=[
            QsarDBArchiveRecord(
                handle="archive-handle",
                archive_id="archive-1",
                title="Example archive",
            )
        ],
        models=[
            QsarDBModelRecord(
                handle="model-handle",
                model_id="model-1",
                endpoint="melting_point",
                model_type="regression",
            )
        ],
        capabilities=[
            QsarDBModelCapability(
                handle="model-handle",
                model_id="model-1",
                endpoint="melting_point",
                model_type="regression",
                prediction_modes=["single"],
                result_names=["mpC"],
                result_units=["C"],
            )
        ],
        predictions=[
            QsarDBPredictionRecord(
                compound_id="compound-1",
                input_structure="CCO",
                canonical_smiles="CCO",
                handle="model-handle",
                model_id="model-1",
                endpoint="melting_point",
                model_type="regression",
                prediction_mode="single",
                status="ok",
                result_name="mpC",
                result_value="13.8",
                result_float=13.8,
                result_unit="C",
                raw_response="mpC = 13.8",
            )
        ],
        extracted_tables=[{"name": "prediction-table", "rows": 1}],
        raw_files=[{"path": "archive.qdb", "sha256": "abc123"}],
    )


def test_records_to_dicts_converts_chemical_record_to_json_compatible_dict() -> None:
    data = records_to_dicts([make_chemical()])

    assert data[0]["compound_id"] == "compound-1"
    assert data[0]["canonical_smiles"] == "CCO"
    json.dumps(data)


def test_records_to_dicts_accepts_plain_dictionary() -> None:
    data = records_to_dicts([{"compound_id": "compound-1", "value": 1}])

    assert data == [{"compound_id": "compound-1", "value": 1}]


def test_records_to_dicts_does_not_mutate_input_dictionary() -> None:
    original = {"compound_id": "compound-1", "value": 1}

    data = records_to_dicts([original])
    data[0]["value"] = 2

    assert original == {"compound_id": "compound-1", "value": 1}


def test_records_to_dataframe_returns_expected_columns() -> None:
    dataframe = records_to_dataframe([make_chemical()])

    assert isinstance(dataframe, pd.DataFrame)
    assert "compound_id" in dataframe.columns
    assert "input_structure" in dataframe.columns
    assert dataframe.loc[0, "compound_id"] == "compound-1"


def test_records_to_csv_writes_file(tmp_path: Path) -> None:
    output_path = records_to_csv([make_chemical()], tmp_path / "exports" / "chemicals.csv")

    assert output_path == tmp_path / "exports" / "chemicals.csv"
    assert output_path.exists()
    assert "compound_id" in output_path.read_text(encoding="utf-8")


def test_records_to_json_writes_json_array(tmp_path: Path) -> None:
    output_path = records_to_json([make_chemical()], tmp_path / "exports" / "chemicals.json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload[0]["compound_id"] == "compound-1"


def test_records_to_parquet_calls_pandas_to_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, *, index: bool = False) -> None:
        calls["path"] = path
        calls["index"] = index
        path.write_bytes(b"PAR1")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)

    output_path = records_to_parquet(
        [make_chemical()],
        tmp_path / "exports" / "chemicals.parquet",
        index=True,
    )

    assert output_path == tmp_path / "exports" / "chemicals.parquet"
    assert calls == {"path": output_path, "index": True}
    assert output_path.read_bytes() == b"PAR1"


@pytest.mark.parametrize("error_type", [ImportError, ValueError])
def test_records_to_parquet_missing_engine_raises_export_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def missing_engine(self: pd.DataFrame, path: Path, *, index: bool = False) -> None:
        raise error_type("missing parquet engine")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", missing_engine)

    with pytest.raises(ExportError, match="Parquet engine"):
        records_to_parquet([make_chemical()], tmp_path / "chemicals.parquet")


def test_evidence_bundle_to_dict_preserves_all_bundle_sections() -> None:
    payload = evidence_bundle_to_dict(make_bundle())

    assert list(payload) == BUNDLE_TABLE_KEYS
    assert payload["chemicals"][0]["compound_id"] == "compound-1"
    assert payload["archives"][0]["handle"] == "archive-handle"
    assert payload["models"][0]["model_id"] == "model-1"
    assert payload["capabilities"][0]["prediction_modes"] == ["single"]
    assert payload["predictions"][0]["raw_response"] == "mpC = 13.8"
    assert payload["extracted_tables"] == [{"name": "prediction-table", "rows": 1}]
    assert payload["raw_files"] == [{"path": "archive.qdb", "sha256": "abc123"}]


def test_evidence_bundle_to_json_writes_full_json_object(tmp_path: Path) -> None:
    output_path = evidence_bundle_to_json(make_bundle(), tmp_path / "bundle.json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert list(payload) == BUNDLE_TABLE_KEYS
    assert payload["predictions"][0]["raw_response"] == "mpC = 13.8"


def test_evidence_bundle_to_tables_returns_expected_tables() -> None:
    tables = evidence_bundle_to_tables(make_bundle())

    assert list(tables) == BUNDLE_TABLE_KEYS
    assert all(isinstance(table, pd.DataFrame) for table in tables.values())


def test_evidence_bundle_to_tables_includes_prediction_raw_response() -> None:
    tables = evidence_bundle_to_tables(make_bundle())

    assert tables["predictions"].loc[0, "raw_response"] == "mpC = 13.8"