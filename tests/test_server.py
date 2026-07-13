from __future__ import annotations

import io
import json

import pandas as pd
from fastapi.testclient import TestClient

from qsardb_client.schemas import QsarDBPredictionRecord
from qsardb_client.server import app


CATALOG_HTML = """
<html>
  <body>
    <h4>Regression models</h4>
    <table>
      <tr>
        <th>Handle</th>
        <th>Model IDs</th>
        <th>Endpoint</th>
      </tr>
      <tr>
        <td>10967/257</td>
        <td>M1</td>
        <td>Intrinsic aqueous solubility</td>
      </tr>
    </table>
  </body>
</html>
"""

COMPOUNDS_CSV = "compound_id,input_structure\ncompound-1,CCO\n"
SINGLE_MODEL = {
    "handle": "10967/257",
    "model_id": "M1",
    "endpoint": "Intrinsic aqueous solubility",
    "model_type": "regression",
}
MODELS_JSON = json.dumps([SINGLE_MODEL])


class FakeRemotePredictorClient:
    init_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).init_kwargs = kwargs

    async def __aenter__(self) -> "FakeRemotePredictorClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def predict_many(self, chemicals, models):
        return [
            QsarDBPredictionRecord(
                compound_id=chemical.compound_id,
                input_structure=chemical.input_structure,
                canonical_smiles=chemical.canonical_smiles,
                handle=model.handle,
                model_id=model.model_id,
                endpoint=model.endpoint,
                model_type=model.model_type,
                prediction_mode="remote_structure_api",
                status="ok",
                result_name="mpC",
                result_value="13.8",
                result_float=13.8,
                raw_response="mpC = 13.8",
            )
            for chemical in chemicals
            for model in models
        ]


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_catalog_refresh_with_uploaded_html_returns_json() -> None:
    response = client.post(
        "/catalog/refresh",
        data={"format": "json"},
        files={"html_file": ("catalog.html", CATALOG_HTML, "text/html")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["handle"] == "10967/257"
    assert payload[0]["model_id"] == "M1"


def test_catalog_refresh_with_uploaded_html_returns_csv() -> None:
    response = client.post(
        "/catalog/refresh",
        data={"format": "csv"},
        files={"html_file": ("catalog.html", CATALOG_HTML, "text/html")},
    )

    assert response.status_code == 200
    dataframe = pd.read_csv(io.BytesIO(response.content))
    assert dataframe.loc[0, "handle"] == "10967/257"


def test_catalog_refresh_without_html_uses_remote_fetch(monkeypatch) -> None:
    def fake_fetch_models(self):
        from qsardb_client.predictor.catalog import parse_predictor_catalog_html

        return parse_predictor_catalog_html(CATALOG_HTML)

    monkeypatch.setattr(
        "qsardb_client.server.PredictorCatalog.fetch_models", fake_fetch_models
    )

    response = client.post("/catalog/refresh", data={"format": "json"})

    assert response.status_code == 200
    assert response.json()[0]["handle"] == "10967/257"


def test_predict_single_model_reads_uploads_and_returns_json(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict",
        data={"format": "json", **SINGLE_MODEL},
        files={"input": ("compounds.csv", COMPOUNDS_CSV, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["compound_id"] == "compound-1"
    assert payload[0]["handle"] == "10967/257"
    assert payload[0]["raw_response"] == "mpC = 13.8"


def test_predict_single_model_returns_csv(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict",
        data={"format": "csv", **SINGLE_MODEL},
        files={"input": ("compounds.csv", COMPOUNDS_CSV, "text/csv")},
    )

    assert response.status_code == 200
    dataframe = pd.read_csv(io.BytesIO(response.content))
    assert len(dataframe) == 1
    assert dataframe.loc[0, "compound_id"] == "compound-1"


def test_predict_single_model_passes_runtime_options_to_remote_client(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict",
        data={
            "format": "json",
            "concurrency": "4",
            "request_delay_seconds": "0.25",
            "retry_delay_seconds": "0.5",
            "retries": "5",
            **SINGLE_MODEL,
        },
        files={"input": ("compounds.csv", COMPOUNDS_CSV, "text/csv")},
    )

    assert response.status_code == 200
    assert FakeRemotePredictorClient.init_kwargs == {
        "retries": 5,
        "retry_delay_seconds": 0.5,
        "request_delay_seconds": 0.25,
        "concurrency": 4,
    }


def test_predict_single_model_returns_400_for_missing_compound_id_column() -> None:
    response = client.post(
        "/predict",
        data={"format": "json", **SINGLE_MODEL},
        files={"input": ("compounds.csv", "wrong_column,input_structure\na,CCO\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "compound_id" in response.json()["detail"]


def test_predict_single_model_returns_422_for_missing_model_field() -> None:
    incomplete_model = {key: value for key, value in SINGLE_MODEL.items() if key != "model_id"}

    response = client.post(
        "/predict",
        data={"format": "json", **incomplete_model},
        files={"input": ("compounds.csv", COMPOUNDS_CSV, "text/csv")},
    )

    assert response.status_code == 422


def test_predict_batch_reads_uploads_and_returns_json(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict/batch",
        data={"format": "json"},
        files={
            "input": ("compounds.csv", COMPOUNDS_CSV, "text/csv"),
            "models": ("models.json", MODELS_JSON, "application/json"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["compound_id"] == "compound-1"
    assert payload[0]["raw_response"] == "mpC = 13.8"


def test_predict_batch_returns_csv(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict/batch",
        data={"format": "csv"},
        files={
            "input": ("compounds.csv", COMPOUNDS_CSV, "text/csv"),
            "models": ("models.json", MODELS_JSON, "application/json"),
        },
    )

    assert response.status_code == 200
    dataframe = pd.read_csv(io.BytesIO(response.content))
    assert dataframe.loc[0, "compound_id"] == "compound-1"


def test_predict_batch_runs_n_compounds_times_m_models(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    two_compounds_csv = "compound_id,input_structure\ncompound-1,CCO\ncompound-2,CC(=O)O\n"
    two_models_json = json.dumps(
        [
            SINGLE_MODEL,
            {**SINGLE_MODEL, "model_id": "M2"},
        ]
    )

    response = client.post(
        "/predict/batch",
        data={"format": "json"},
        files={
            "input": ("compounds.csv", two_compounds_csv, "text/csv"),
            "models": ("models.json", two_models_json, "application/json"),
        },
    )

    assert response.status_code == 200
    assert len(response.json()) == 4


def test_predict_batch_passes_runtime_options_to_remote_client(monkeypatch) -> None:
    monkeypatch.setattr("qsardb_client.server.RemotePredictorClient", FakeRemotePredictorClient)

    response = client.post(
        "/predict/batch",
        data={
            "format": "json",
            "concurrency": "4",
            "request_delay_seconds": "0.25",
            "retry_delay_seconds": "0.5",
            "retries": "5",
        },
        files={
            "input": ("compounds.csv", COMPOUNDS_CSV, "text/csv"),
            "models": ("models.json", MODELS_JSON, "application/json"),
        },
    )

    assert response.status_code == 200
    assert FakeRemotePredictorClient.init_kwargs == {
        "retries": 5,
        "retry_delay_seconds": 0.5,
        "request_delay_seconds": 0.25,
        "concurrency": 4,
    }


def test_predict_batch_returns_400_for_missing_compound_id_column() -> None:
    response = client.post(
        "/predict/batch",
        data={"format": "json"},
        files={
            "input": ("compounds.csv", "wrong_column,input_structure\na,CCO\n", "text/csv"),
            "models": ("models.json", MODELS_JSON, "application/json"),
        },
    )

    assert response.status_code == 400
    assert "compound_id" in response.json()["detail"]


def test_predict_batch_returns_400_for_invalid_models_json_shape() -> None:
    response = client.post(
        "/predict/batch",
        data={"format": "json"},
        files={
            "input": ("compounds.csv", COMPOUNDS_CSV, "text/csv"),
            "models": ("models.json", json.dumps({"not": "a list"}), "application/json"),
        },
    )

    assert response.status_code == 400
    assert "JSON array" in response.json()["detail"]
