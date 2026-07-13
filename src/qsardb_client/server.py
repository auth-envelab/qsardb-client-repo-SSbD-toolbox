"""HTTP API that exposes accepted QsarDB client capabilities over REST.

This mirrors the ``qsardb-client`` CLI (catalogue refresh and remote
prediction) so a caller platform can integrate over HTTP instead of
shelling out to the CLI. It carries the same implementation scope as the
CLI: no SSbD scoring, hazard classification, or regulatory interpretation
is performed here.
"""

from __future__ import annotations

import io
import json
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from qsardb_client.chemistry.standardize import (
    ChemistryNormalizationError,
    normalize_chemical_records,
)
from qsardb_client.export import ExportError, records_to_dataframe, records_to_dicts
from qsardb_client.io_utils import read_compounds_csv, read_models_json
from qsardb_client.predictor.catalog import PredictorCatalog, parse_predictor_catalog_html
from qsardb_client.predictor.remote import RemotePredictorClient
from qsardb_client.schemas import QsarDBModelRecord, QsarDBPredictionRecord


app = FastAPI(
    title="qsardb-client",
    description=(
        "QsarDB-native integration layer: predictor catalogue refresh and "
        "remote structure-callable predictions. Not an SSbD scoring service."
    ),
    version="0.1.0",
)

_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
}

_KNOWN_ERRORS = (
    OSError,
    ValueError,
    json.JSONDecodeError,
    ValidationError,
    ChemistryNormalizationError,
    ExportError,
)


def _serialize_records(
    records: list[QsarDBModelRecord] | list[QsarDBPredictionRecord],
    fmt: Literal["json", "csv", "parquet"],
) -> bytes:
    if fmt == "json":
        return json.dumps(records_to_dicts(records), indent=2).encode("utf-8")

    dataframe = records_to_dataframe(records)
    if fmt == "csv":
        return dataframe.to_csv(index=False).encode("utf-8")

    buffer = io.BytesIO()
    try:
        dataframe.to_parquet(buffer, index=False)
    except (ImportError, ValueError) as exc:
        raise ExportError(
            "Writing Parquet requires an optional pandas Parquet engine such as "
            "pyarrow or fastparquet. Install one of those engines and retry."
        ) from exc
    return buffer.getvalue()


def _file_response(payload: bytes, fmt: Literal["json", "csv", "parquet"], basename: str) -> Response:
    return Response(
        content=payload,
        media_type=_CONTENT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{basename}.{fmt}"'},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/catalog/refresh")
def catalog_refresh(
    format: Literal["json", "csv"] = Form("json"),
    html_file: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """Fetch (or parse an uploaded copy of) the QsarDB predictor catalogue."""

    try:
        if html_file is not None:
            html = html_file.file.read().decode("utf-8")
            records = parse_predictor_catalog_html(html)
        else:
            records = PredictorCatalog().fetch_models()
        payload = _serialize_records(records, format)
    except _KNOWN_ERRORS as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc

    return _file_response(payload, format, "models")


async def _run_predict(
    *,
    input_file: UploadFile,
    models: list[QsarDBModelRecord],
    format: Literal["json", "csv", "parquet"],
    require_rdkit: bool,
    concurrency: int,
    request_delay_seconds: float,
    retry_delay_seconds: float,
    retries: int,
) -> Response:
    try:
        compound_rows = read_compounds_csv(io.BytesIO(await input_file.read()))
        chemicals = normalize_chemical_records(compound_rows, require_rdkit=require_rdkit)

        async with RemotePredictorClient(
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
            request_delay_seconds=request_delay_seconds,
            concurrency=concurrency,
        ) as predictor:
            predictions = await predictor.predict_many(chemicals, models)

        payload = _serialize_records(predictions, format)
    except _KNOWN_ERRORS as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc

    return _file_response(payload, format, "predictions")


@app.post("/predict")
async def predict(
    input: Annotated[UploadFile, File(description="Compounds CSV: compound_id,input_structure")],
    handle: Annotated[str, Form(description="QsarDB archive handle, e.g. 10967/257")],
    model_id: Annotated[str, Form(description="Model id within the archive, e.g. M1")],
    endpoint: Annotated[str, Form(description="Predicted endpoint label")],
    model_type: Annotated[str, Form(description="'regression' or 'classification'")],
    format: Literal["json", "csv", "parquet"] = Form("json"),
    require_rdkit: bool = Form(False),
    concurrency: int = Form(2),
    request_delay_seconds: float = Form(0.0),
    retry_delay_seconds: float = Form(0.0),
    retries: int = Form(2),
) -> Response:
    """Run remote QsarDB predictions for uploaded compounds against a single model."""

    try:
        model = QsarDBModelRecord(
            handle=handle,
            model_id=model_id,
            endpoint=endpoint,
            model_type=model_type,
        )
    except _KNOWN_ERRORS as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc

    return await _run_predict(
        input_file=input,
        models=[model],
        format=format,
        require_rdkit=require_rdkit,
        concurrency=concurrency,
        request_delay_seconds=request_delay_seconds,
        retry_delay_seconds=retry_delay_seconds,
        retries=retries,
    )


@app.post("/predict/batch")
async def predict_batch(
    input: Annotated[UploadFile, File(description="Compounds CSV: compound_id,input_structure")],
    models: Annotated[UploadFile, File(description="Predictor models JSON array")],
    format: Literal["json", "csv", "parquet"] = Form("json"),
    require_rdkit: bool = Form(False),
    concurrency: int = Form(2),
    request_delay_seconds: float = Form(0.0),
    retry_delay_seconds: float = Form(0.0),
    retries: int = Form(2),
) -> Response:
    """Run remote QsarDB predictions for uploaded compounds against many models."""

    try:
        model_records = read_models_json(io.BytesIO(await models.read()))
    except _KNOWN_ERRORS as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc

    return await _run_predict(
        input_file=input,
        models=model_records,
        format=format,
        require_rdkit=require_rdkit,
        concurrency=concurrency,
        request_delay_seconds=request_delay_seconds,
        retry_delay_seconds=retry_delay_seconds,
        retries=retries,
    )


def run() -> None:
    """Entry point for the ``qsardb-client-server`` console script."""

    import os

    import uvicorn

    uvicorn.run(
        "qsardb_client.server:app",
        host=os.environ.get("QSARDB_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("QSARDB_SERVER_PORT", "8000")),
    )


if __name__ == "__main__":
    run()
