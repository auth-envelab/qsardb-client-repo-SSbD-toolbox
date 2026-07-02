from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from qsardb_client.cli import main
from qsardb_client.schemas import QsarDBModelRecord, QsarDBPredictionRecord


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


def write_compounds_csv(path: Path) -> None:
    path.write_text("compound_id,input_structure\ncompound-1,CCO\n", encoding="utf-8")


def write_models_json(path: Path) -> None:
    payload = [
        {
            "handle": "10967/257",
            "model_id": "M1",
            "endpoint": "Intrinsic aqueous solubility",
            "model_type": "regression",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_main_help_returns_zero(capsys) -> None:
    assert main(["--help"]) == 0
    assert "qsardb-client" in capsys.readouterr().out


def test_module_style_entry_point_is_importable() -> None:
    from qsardb_client.cli import main as imported_main

    assert imported_main is main


def test_catalog_refresh_html_file_writes_json(tmp_path: Path) -> None:
    html_path = tmp_path / "catalog.html"
    out_path = tmp_path / "models.json"
    html_path.write_text(CATALOG_HTML, encoding="utf-8")

    assert main(["catalog", "refresh", "--html-file", str(html_path), "--out", str(out_path), "--format", "json"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload[0]["handle"] == "10967/257"
    assert payload[0]["model_id"] == "M1"


def test_catalog_refresh_html_file_writes_csv(tmp_path: Path) -> None:
    html_path = tmp_path / "catalog.html"
    out_path = tmp_path / "models.csv"
    html_path.write_text(CATALOG_HTML, encoding="utf-8")

    assert main(["catalog", "refresh", "--html-file", str(html_path), "--out", str(out_path), "--format", "csv"]) == 0

    dataframe = pd.read_csv(out_path)
    assert dataframe.loc[0, "handle"] == "10967/257"


def test_catalog_refresh_without_html_file_uses_catalog_fetch(monkeypatch, tmp_path: Path) -> None:
    out_path = tmp_path / "models.json"
    calls = {"count": 0}

    def fake_fetch_models(self) -> list[QsarDBModelRecord]:
        calls["count"] += 1
        return [
            QsarDBModelRecord(
                handle="10967/257",
                model_id="M1",
                endpoint="Intrinsic aqueous solubility",
                model_type="regression",
            )
        ]

    monkeypatch.setattr("qsardb_client.cli.PredictorCatalog.fetch_models", fake_fetch_models)

    assert main(["catalog", "refresh", "--out", str(out_path), "--format", "json"]) == 0

    assert calls == {"count": 1}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload[0]["model_id"] == "M1"


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


def test_predict_reads_inputs_and_writes_json(monkeypatch, tmp_path: Path) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    out_path = tmp_path / "predictions.json"
    write_compounds_csv(compounds_path)
    write_models_json(models_path)
    monkeypatch.setattr("qsardb_client.cli.RemotePredictorClient", FakeRemotePredictorClient)

    assert main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(out_path), "--format", "json"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload[0]["compound_id"] == "compound-1"
    assert payload[0]["input_structure"] == "CCO"
    assert payload[0]["raw_response"] == "mpC = 13.8"


def test_predict_writes_csv(monkeypatch, tmp_path: Path) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    out_path = tmp_path / "predictions.csv"
    write_compounds_csv(compounds_path)
    write_models_json(models_path)
    monkeypatch.setattr("qsardb_client.cli.RemotePredictorClient", FakeRemotePredictorClient)

    assert main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(out_path), "--format", "csv"]) == 0

    dataframe = pd.read_csv(out_path)
    assert dataframe.loc[0, "compound_id"] == "compound-1"
    assert dataframe.loc[0, "raw_response"] == "mpC = 13.8"


def test_predict_writes_parquet_with_monkeypatched_export(monkeypatch, tmp_path: Path) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    out_path = tmp_path / "predictions.parquet"
    calls: dict[str, object] = {}
    write_compounds_csv(compounds_path)
    write_models_json(models_path)
    monkeypatch.setattr("qsardb_client.cli.RemotePredictorClient", FakeRemotePredictorClient)

    def fake_records_to_parquet(records, path):
        calls["records"] = list(records)
        calls["path"] = path
        path.write_bytes(b"PAR1")
        return path

    monkeypatch.setattr("qsardb_client.cli.records_to_parquet", fake_records_to_parquet)

    assert main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(out_path), "--format", "parquet"]) == 0

    assert calls["path"] == out_path
    assert out_path.read_bytes() == b"PAR1"


def test_predict_returns_nonzero_for_missing_compound_id_column(tmp_path: Path, capsys) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    compounds_path.write_text("input_structure\nCCO\n", encoding="utf-8")
    write_models_json(models_path)

    result = main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(tmp_path / "out.json"), "--format", "json"])

    assert result != 0
    assert "compound_id" in capsys.readouterr().err


def test_predict_returns_nonzero_for_missing_input_structure_column(tmp_path: Path, capsys) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    compounds_path.write_text("compound_id\ncompound-1\n", encoding="utf-8")
    write_models_json(models_path)

    result = main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(tmp_path / "out.json"), "--format", "json"])

    assert result != 0
    assert "input_structure" in capsys.readouterr().err


def test_predict_returns_nonzero_for_invalid_models_json_shape(tmp_path: Path, capsys) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    write_compounds_csv(compounds_path)
    models_path.write_text(json.dumps({"handle": "10967/257"}), encoding="utf-8")

    result = main(["predict", "--input", str(compounds_path), "--models", str(models_path), "--out", str(tmp_path / "out.json"), "--format", "json"])

    assert result != 0
    assert "JSON array" in capsys.readouterr().err


def test_predict_passes_runtime_options_to_remote_client(monkeypatch, tmp_path: Path) -> None:
    compounds_path = tmp_path / "compounds.csv"
    models_path = tmp_path / "models.json"
    out_path = tmp_path / "predictions.json"
    cache_dir = tmp_path / "cache"
    write_compounds_csv(compounds_path)
    write_models_json(models_path)
    monkeypatch.setattr("qsardb_client.cli.RemotePredictorClient", FakeRemotePredictorClient)

    assert main([
        "predict",
        "--input",
        str(compounds_path),
        "--models",
        str(models_path),
        "--out",
        str(out_path),
        "--format",
        "json",
        "--cache-dir",
        str(cache_dir),
        "--concurrency",
        "5",
        "--retries",
        "4",
        "--request-delay-seconds",
        "0.25",
        "--retry-delay-seconds",
        "0.5",
    ]) == 0

    assert FakeRemotePredictorClient.init_kwargs == {
        "cache_dir": cache_dir,
        "retries": 4,
        "retry_delay_seconds": 0.5,
        "request_delay_seconds": 0.25,
        "concurrency": 5,
    }


def test_no_archive_repository_or_ssbd_commands_exist(capsys) -> None:
    for command in ("archive", "repository", "ssbd"):
        result = main([command, "--help"])
        assert result != 0

    assert "invalid choice" in capsys.readouterr().err
