import json

import pandas as pd
import pytest

from qsardb_client.run import (
    RunSummaryError,
    create_run_metadata,
    predictions_to_dataframe,
    summarize_by_compound,
    summarize_by_endpoint,
    summarize_by_model,
    summarize_errors,
    write_run_summary_files,
)
from qsardb_client.schemas import QsarDBPredictionRecord


def _prediction_rows() -> list[dict[str, object]]:
    return [
        {
            "compound_id": "c1",
            "input_structure": "CCO",
            "canonical_smiles": "CCO",
            "handle": "10967/1",
            "model_id": "M1",
            "endpoint": "Endpoint A",
            "model_type": "regression",
            "prediction_mode": "smiles",
            "status": "ok",
            "result_name": "value",
            "result_value": "1.0",
            "result_float": 1.0,
            "result_unit": "unit",
            "raw_response": "mpC = 13.8",
            "error": "",
        },
        {
            "compound_id": "c2",
            "input_structure": "CC(=O)O",
            "canonical_smiles": "CC(=O)O",
            "handle": "10967/1",
            "model_id": "M1",
            "endpoint": "Endpoint A",
            "model_type": "regression",
            "prediction_mode": "smiles",
            "status": "error",
            "result_name": None,
            "result_value": None,
            "result_float": None,
            "result_unit": None,
            "raw_response": "raw error response",
            "error": "",
        },
        {
            "compound_id": "c1",
            "input_structure": "CCO",
            "canonical_smiles": "CCO",
            "handle": "10967/2",
            "model_id": "M2",
            "endpoint": "Endpoint B",
            "model_type": "classification",
            "prediction_mode": "smiles",
            "status": "ok",
            "result_name": "class",
            "result_value": "active",
            "result_float": None,
            "result_unit": None,
            "raw_response": "class = active",
            "error": "warning text",
        },
        {
            "compound_id": "c2",
            "input_structure": "CC(=O)O",
            "canonical_smiles": "CC(=O)O",
            "handle": "10967/2",
            "model_id": "M2",
            "endpoint": "Endpoint B",
            "model_type": "classification",
            "prediction_mode": "smiles",
            "status": "ok",
            "result_name": "class",
            "result_value": "inactive",
            "result_float": None,
            "result_unit": None,
            "raw_response": "class = inactive",
            "error": "",
        },
    ]


def _predictions_df() -> pd.DataFrame:
    return pd.DataFrame(_prediction_rows())


def test_predictions_to_dataframe_accepts_dataframe_and_returns_copy():
    original = _predictions_df()

    result = predictions_to_dataframe(original)
    result.loc[0, "status"] = "changed"

    assert result is not original
    assert original.loc[0, "status"] == "ok"


def test_predictions_to_dataframe_accepts_prediction_records_and_preserves_raw_response():
    records = [QsarDBPredictionRecord(**row) for row in _prediction_rows()[:2]]

    result = predictions_to_dataframe(records)

    assert result["raw_response"].tolist() == ["mpC = 13.8", "raw error response"]
    assert result["compound_id"].tolist() == ["c1", "c2"]


def test_predictions_to_dataframe_accepts_dictionaries_and_preserves_raw_response():
    result = predictions_to_dataframe(_prediction_rows())

    assert result.loc[0, "raw_response"] == "mpC = 13.8"
    assert result.loc[1, "error"] == ""


def test_predictions_to_dataframe_rejects_unsupported_inputs():
    with pytest.raises(RunSummaryError):
        predictions_to_dataframe(object())
    with pytest.raises(RunSummaryError):
        predictions_to_dataframe([object()])


def test_summarize_by_endpoint_groups_dynamically():
    summary = summarize_by_endpoint(_predictions_df())

    assert summary.to_dict("records") == [
        {"endpoint": "Endpoint A", "model_id": "M1", "status": "error", "n": 1},
        {"endpoint": "Endpoint A", "model_id": "M1", "status": "ok", "n": 1},
        {"endpoint": "Endpoint B", "model_id": "M2", "status": "ok", "n": 2},
    ]


def test_summarize_by_model_groups_dynamically():
    summary = summarize_by_model(_predictions_df())

    assert summary["n"].sum() == 4
    assert summary.loc[summary["status"].eq("error"), "n"].item() == 1


def test_summarize_by_compound_groups_dynamically():
    summary = summarize_by_compound(_predictions_df())

    assert summary.to_dict("records") == [
        {"compound_id": "c1", "status": "ok", "n": 2},
        {"compound_id": "c2", "status": "error", "n": 1},
        {"compound_id": "c2", "status": "ok", "n": 1},
    ]


def test_summarize_errors_includes_status_errors_non_empty_errors_and_empty_text():
    summary = summarize_errors(_predictions_df())

    assert summary.to_dict("records") == [
        {
            "handle": "10967/1",
            "model_id": "M1",
            "endpoint": "Endpoint A",
            "model_type": "regression",
            "error": "<no error text>",
            "n": 1,
        },
        {
            "handle": "10967/2",
            "model_id": "M2",
            "endpoint": "Endpoint B",
            "model_type": "classification",
            "error": "warning text",
            "n": 1,
        },
    ]


@pytest.mark.parametrize(
    "summary_func",
    [summarize_by_endpoint, summarize_by_model, summarize_by_compound, summarize_errors],
)
def test_summary_functions_raise_for_missing_required_columns(summary_func):
    df = _predictions_df().drop(columns=["handle"])

    with pytest.raises(RunSummaryError, match="handle"):
        summary_func(df)


def test_create_run_metadata_uses_dynamic_n_for_two_inputs():
    predictions = _predictions_df()
    input_compounds = pd.DataFrame([{"compound_id": "c1"}, {"compound_id": "c2"}])
    models = pd.DataFrame(
        [
            {"handle": "10967/1", "model_id": "M1"},
            {"handle": "10967/2", "model_id": "M2"},
        ]
    )

    metadata = create_run_metadata(
        predictions=predictions,
        models=models,
        input_compounds=input_compounds,
        generated_at="2026-07-01T00:00:00+00:00",
    )

    assert metadata["number_of_input_substances"] == 2
    assert metadata["number_of_models"] == 2
    assert metadata["expected_prediction_records"] == 4
    assert metadata["expected_prediction_records"] != 100 * 2
    assert metadata["all_compound_model_pairs_present"] is True


def test_create_run_metadata_uses_dynamic_n_for_five_inputs():
    rows = []
    compounds = [{"compound_id": f"c{i}"} for i in range(5)]
    models = [{"handle": "10967/1", "model_id": "M1"}]
    for compound in compounds:
        row = dict(_prediction_rows()[0])
        row["compound_id"] = compound["compound_id"]
        rows.append(row)

    metadata = create_run_metadata(
        predictions=rows,
        models=models,
        input_compounds=compounds,
    )

    assert metadata["number_of_input_substances"] == 5
    assert metadata["expected_prediction_records"] == 5
    assert metadata["missing_prediction_records"] == 0


def test_create_run_metadata_infers_counts_from_predictions():
    metadata = create_run_metadata(predictions=_predictions_df())

    assert metadata["number_of_input_substances"] == 2
    assert metadata["input_substance_count_source"] == "predictions_unique_compound_id"
    assert metadata["number_of_models"] == 2
    assert metadata["model_count_source"] == "predictions_unique_handle_model_id"
    assert metadata["expected_prediction_records"] == 4


def test_create_run_metadata_detects_missing_compound_model_pairs():
    predictions = _predictions_df().iloc[:3]
    input_compounds = [{"compound_id": "c1"}, {"compound_id": "c2"}]
    models = [
        {"handle": "10967/1", "model_id": "M1"},
        {"handle": "10967/2", "model_id": "M2"},
    ]

    metadata = create_run_metadata(
        predictions=predictions,
        models=models,
        input_compounds=input_compounds,
    )

    assert metadata["expected_prediction_records"] == 4
    assert metadata["actual_prediction_records"] == 3
    assert metadata["missing_prediction_records"] == 1
    assert metadata["all_compound_model_pairs_present"] is False


def test_write_run_summary_files_creates_expected_outputs(tmp_path):
    paths = write_run_summary_files(
        predictions=_predictions_df(),
        output_dir=tmp_path,
        models=[
            {"handle": "10967/1", "model_id": "M1"},
            {"handle": "10967/2", "model_id": "M2"},
        ],
        input_compounds=[{"compound_id": "c1"}, {"compound_id": "c2"}],
        input_file="input.csv",
        models_file="models.json",
        predictions_file="predictions.csv",
    )

    assert set(paths) == {
        "endpoint_status_summary",
        "compound_status_summary",
        "model_status_summary",
        "model_error_summary",
        "run_metadata",
    }
    assert all(path.exists() for path in paths.values())
    metadata = json.loads(paths["run_metadata"].read_text(encoding="utf-8"))
    assert metadata["input_file"] == "input.csv"
    assert metadata["expected_prediction_records"] == 4


def test_run_metadata_has_no_ssbd_hazard_weighting_or_regulatory_fields():
    metadata = create_run_metadata(predictions=_predictions_df())

    disallowed_terms = ("ssbd", "hazard", "weight", "regulatory")
    assert not any(
        term in key.lower()
        for key in metadata
        for term in disallowed_terms
    )
