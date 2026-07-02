from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from qsardb_client import ChemicalRecord, QsarDBClient
from qsardb_client.schemas import (
    QsarDBArchiveRecord,
    QsarDBEvidenceBundle,
    QsarDBModelCapability,
    QsarDBModelRecord,
    QsarDBPredictionRecord,
)


def assert_serializable(record: object) -> None:
    data = record.model_dump(mode="json")
    json.dumps(data)
    assert json.loads(record.model_dump_json()) == data


def test_public_imports_work() -> None:
    client = QsarDBClient(base_url="https://example.invalid")

    assert client.base_url == "https://example.invalid"
    assert ChemicalRecord(compound_id="c1", input_structure="CCO")


def test_chemical_record_serializes_and_requires_fields() -> None:
    record = ChemicalRecord(
        compound_id="compound-1",
        input_structure="CCO",
        canonical_smiles="CCO",
        handle="QDB-001",
    )

    assert record.model_dump()["compound_id"] == "compound-1"
    assert_serializable(record)

    with pytest.raises(ValidationError):
        ChemicalRecord(input_structure="CCO")


def test_archive_record_serializes_and_requires_fields() -> None:
    record = QsarDBArchiveRecord(
        handle="archive-handle",
        archive_id="archive-1",
        title="Example archive",
        source_url="https://example.invalid/archive.qdb",
    )

    assert record.model_dump()["handle"] == "archive-handle"
    assert record.model_dump()["archive_id"] == "archive-1"
    assert_serializable(record)

    with pytest.raises(ValidationError):
        QsarDBArchiveRecord(archive_id="archive-1", title="Missing handle")


def test_model_record_serializes_and_requires_fields() -> None:
    record = QsarDBModelRecord(
        handle="model-handle",
        model_id="model-1",
        archive_id="archive-1",
        endpoint="logKow",
        model_type="regression",
    )

    assert record.model_dump()["handle"] == "model-handle"
    assert record.model_dump()["endpoint"] == "logKow"
    assert_serializable(record)

    with pytest.raises(ValidationError):
        QsarDBModelRecord(
            model_id="model-1",
            endpoint="logKow",
            model_type="regression",
        )


def test_model_capability_serializes_and_requires_fields() -> None:
    record = QsarDBModelCapability(
        handle="capability-handle",
        model_id="model-1",
        endpoint="logKow",
        model_type="regression",
        prediction_modes=["single"],
        result_names=["logKow"],
        result_units=["log10"],
        applicability_domain_available=True,
    )

    assert record.model_dump()["handle"] == "capability-handle"
    assert record.model_dump()["prediction_modes"] == ["single"]
    assert_serializable(record)

    with pytest.raises(ValidationError):
        QsarDBModelCapability(
            model_id="model-1",
            endpoint="logKow",
            model_type="regression",
        )


def test_prediction_record_preserves_required_fields() -> None:
    predicted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    raw_response = "mpC = 13.8"
    similar_compounds = [{"compound_id": "compound-2", "similarity": 0.91}]
    record = QsarDBPredictionRecord(
        compound_id="compound-1",
        input_structure="CCO",
        canonical_smiles="CCO",
        handle="prediction-handle",
        model_id="model-1",
        endpoint="logKow",
        model_type="regression",
        prediction_mode="single",
        status="success",
        result_name="logKow",
        result_value="1.23",
        result_float=1.23,
        result_unit="log10",
        raw_response=raw_response,
        applicability_domain={"inside": True, "score": 0.87},
        similar_compounds=similar_compounds,
        error=None,
        predicted_at=predicted_at,
    )

    dumped = record.model_dump()
    assert dumped["compound_id"] == "compound-1"
    assert dumped["input_structure"] == "CCO"
    assert dumped["canonical_smiles"] == "CCO"
    assert dumped["handle"] == "prediction-handle"
    assert dumped["model_id"] == "model-1"
    assert dumped["endpoint"] == "logKow"
    assert dumped["model_type"] == "regression"
    assert dumped["prediction_mode"] == "single"
    assert dumped["status"] == "success"
    assert dumped["result_name"] == "logKow"
    assert dumped["result_value"] == "1.23"
    assert dumped["result_float"] == 1.23
    assert dumped["result_unit"] == "log10"
    assert dumped["raw_response"] == raw_response
    assert dumped["applicability_domain"] == {"inside": True, "score": 0.87}
    assert dumped["similar_compounds"] == similar_compounds
    assert dumped["error"] is None
    assert dumped["predicted_at"] == predicted_at
    assert_serializable(record)

    with pytest.raises(ValidationError):
        QsarDBPredictionRecord(
            compound_id="compound-1",
            input_structure="CCO",
            model_id="model-1",
            endpoint="logKow",
            model_type="regression",
            prediction_mode="single",
            status="success",
        )


def test_evidence_bundle_contains_required_collections() -> None:
    chemical = ChemicalRecord(compound_id="compound-1", input_structure="CCO")
    archive = QsarDBArchiveRecord(handle="archive-handle", archive_id="archive-1")
    model = QsarDBModelRecord(
        handle="model-handle",
        model_id="model-1",
        endpoint="logKow",
        model_type="regression",
    )
    capability = QsarDBModelCapability(
        handle="capability-handle",
        model_id="model-1",
        endpoint="logKow",
        model_type="regression",
    )
    prediction = QsarDBPredictionRecord(
        compound_id="compound-1",
        input_structure="CCO",
        handle="prediction-handle",
        model_id="model-1",
        endpoint="logKow",
        model_type="regression",
        prediction_mode="single",
        status="success",
    )
    bundle = QsarDBEvidenceBundle(
        chemicals=[chemical],
        archives=[archive],
        models=[model],
        capabilities=[capability],
        predictions=[prediction],
        extracted_tables=[{"name": "predictions", "rows": 1}],
        raw_files=[{"path": "archive.qdb", "sha256": "abc123"}],
    )

    dumped = bundle.model_dump()
    assert dumped["chemicals"][0]["compound_id"] == "compound-1"
    assert dumped["archives"][0]["archive_id"] == "archive-1"
    assert dumped["models"][0]["model_id"] == "model-1"
    assert dumped["capabilities"][0]["model_id"] == "model-1"
    assert dumped["predictions"][0]["model_id"] == "model-1"
    assert dumped["extracted_tables"] == [{"name": "predictions", "rows": 1}]
    assert dumped["raw_files"] == [{"path": "archive.qdb", "sha256": "abc123"}]
    assert_serializable(bundle)
