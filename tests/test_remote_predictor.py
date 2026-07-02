from __future__ import annotations

import httpx
import pytest

from qsardb_client.predictor import RemotePredictorClient
from qsardb_client.schemas import ChemicalRecord, QsarDBModelRecord, QsarDBPredictionRecord


def chemical(
    *,
    compound_id: str = "compound-1",
    input_structure: str = "CCO",
    canonical_smiles: str | None = None,
) -> ChemicalRecord:
    return ChemicalRecord(
        compound_id=compound_id,
        input_structure=input_structure,
        canonical_smiles=canonical_smiles,
    )


def model(
    *,
    handle: str = "10967/104",
    model_id: str = "M1",
    endpoint: str = "Melting point",
    model_type: str = "regression",
) -> QsarDBModelRecord:
    return QsarDBModelRecord(
        handle=handle,
        model_id=model_id,
        endpoint=endpoint,
        model_type=model_type,
    )


@pytest.mark.asyncio
async def test_build_url_preserves_handle_slash_and_encodes_model_and_structure() -> None:
    client = RemotePredictorClient(base_url="https://example.invalid/predictor")

    url = client.build_url(
        handle="10967/104",
        model_id="Tab 3/Model",
        structure="CCO/N=C",
    )

    assert url == (
        "https://example.invalid/predictor/10967/104/models/"
        "Tab%203%2FModel?CCO%2FN%3DC"
    )


@pytest.mark.asyncio
async def test_predict_one_success_returns_parsed_prediction_record() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text="mpC = 13.8")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as http_client:
        predictor = RemotePredictorClient(
            base_url="https://example.invalid/predictor",
            client=http_client,
            retries=0,
        )
        record = await predictor.predict_one(chemical(), model())

    assert isinstance(record, QsarDBPredictionRecord)
    assert record.status == "ok"
    assert record.compound_id == "compound-1"
    assert record.input_structure == "CCO"
    assert record.canonical_smiles is None
    assert record.handle == "10967/104"
    assert record.model_id == "M1"
    assert record.endpoint == "Melting point"
    assert record.model_type == "regression"
    assert record.prediction_mode == "remote_structure_api"
    assert record.result_name == "mpC"
    assert record.result_value == "13.8"
    assert record.result_float == 13.8
    assert record.raw_response == "mpC = 13.8"
    assert record.error is None
    assert seen_urls == ["https://example.invalid/predictor/10967/104/models/M1?CCO"]


@pytest.mark.asyncio
async def test_predict_one_404_returns_error_without_retry() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, text="Not found")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(client=http_client, retries=3)
        record = await predictor.predict_one(chemical(), model())

    assert call_count == 1
    assert record.status == "error"
    assert record.raw_response == "Not found"
    assert "HTTP 404" in (record.error or "")


@pytest.mark.asyncio
async def test_predict_one_retries_transient_http_status_then_succeeds() -> None:
    responses = [httpx.Response(500, text="Temporary"), httpx.Response(200, text="mpC = 9")]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(
            client=http_client,
            retries=2,
            retry_delay_seconds=0.0,
        )
        record = await predictor.predict_one(chemical(), model())

    assert record.status == "ok"
    assert record.result_float == 9.0
    assert responses == []


@pytest.mark.asyncio
async def test_predict_one_retries_request_error_when_retries_allow_it() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("temporary network issue", request=request)
        return httpx.Response(200, text="class = active")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(
            client=http_client,
            retries=1,
            retry_delay_seconds=0.0,
        )
        record = await predictor.predict_one(chemical(), model(model_type="classification"))

    assert call_count == 2
    assert record.status == "ok"
    assert record.result_name == "class"
    assert record.result_value == "active"
    assert record.result_float is None


@pytest.mark.asyncio
async def test_cache_hit_avoids_http_call(tmp_path) -> None:
    call_count = 0
    predictor = RemotePredictorClient(
        base_url="https://example.invalid/predictor",
        cache_dir=tmp_path,
        retries=0,
    )
    chem = chemical()
    mdl = model()
    cache_path = predictor._cache_path(  # noqa: SLF001
        structure=chem.input_structure,
        handle=mdl.handle,
        model_id=mdl.model_id,
    )
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("mpC = 12.5", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text="mpC = 99")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor._client = http_client  # noqa: SLF001
        predictor._owns_client = False  # noqa: SLF001
        record = await predictor.predict_one(chem, mdl)

    assert call_count == 0
    assert record.status == "ok"
    assert record.prediction_mode == "remote_structure_api"
    assert record.raw_response == "mpC = 12.5"
    assert record.result_float == 12.5


@pytest.mark.asyncio
async def test_predict_many_returns_one_record_per_chemical_model_pair() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="mpC = 1")

    chemicals = [
        chemical(compound_id="compound-1", input_structure="CCO"),
        chemical(compound_id="compound-2", input_structure="CCC"),
    ]
    models = [
        model(model_id="M1"),
        model(model_id="M2", endpoint="Boiling point"),
    ]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(client=http_client, concurrency=2)
        records = await predictor.predict_many(chemicals, models)

    assert len(records) == 4
    assert [(record.compound_id, record.model_id) for record in records] == [
        ("compound-1", "M1"),
        ("compound-1", "M2"),
        ("compound-2", "M1"),
        ("compound-2", "M2"),
    ]
    assert all(record.status == "ok" for record in records)


@pytest.mark.asyncio
async def test_predict_one_uses_canonical_smiles_when_present() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text="mpC = 2")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(
            base_url="https://example.invalid/predictor",
            client=http_client,
        )
        record = await predictor.predict_one(
            chemical(input_structure="original", canonical_smiles="C=C"),
            model(),
        )

    assert seen_urls == ["https://example.invalid/predictor/10967/104/models/M1?C%3DC"]
    assert record.input_structure == "original"
    assert record.canonical_smiles == "C=C"


@pytest.mark.asyncio
async def test_predict_one_uses_input_structure_when_canonical_smiles_absent() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text="mpC = 2")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        predictor = RemotePredictorClient(
            base_url="https://example.invalid/predictor",
            client=http_client,
        )
        record = await predictor.predict_one(
            chemical(input_structure="N#N", canonical_smiles=None),
            model(),
        )

    assert seen_urls == ["https://example.invalid/predictor/10967/104/models/M1?N%23N"]
    assert record.input_structure == "N#N"
    assert record.canonical_smiles is None
