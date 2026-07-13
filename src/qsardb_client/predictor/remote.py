"""Async remote client for the QsarDB predictor endpoint."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import TracebackType
from urllib.parse import quote

import httpx

from qsardb_client.predictor.response_parser import parse_prediction_response
from qsardb_client.schemas import ChemicalRecord, QsarDBModelRecord, QsarDBPredictionRecord


DEFAULT_PREDICTOR_BASE_URL = "https://qsardb.org/repository/service/predictor"
_PREDICTION_MODE = "remote_structure_api"
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class RemotePredictorClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_PREDICTOR_BASE_URL,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.AsyncClient | None = None,
        cache_dir: str | Path | None = None,
        retries: int = 2,
        retry_delay_seconds: float = 0.0,
        request_delay_seconds: float = 0.0,
        concurrency: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.retries = max(0, retries)
        self.retry_delay_seconds = retry_delay_seconds
        self.request_delay_seconds = request_delay_seconds
        self.concurrency = max(1, concurrency)

    async def __aenter__(self) -> "RemotePredictorClient":
        self._get_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def build_url(self, *, handle: str, model_id: str, structure: str) -> str:
        encoded_handle = quote(handle.strip("/"), safe="/")
        encoded_model = quote(model_id, safe="")
        encoded_structure = quote(structure, safe="")
        return f"{self.base_url}/{encoded_handle}/models/{encoded_model}?{encoded_structure}"

    async def predict_one(
        self,
        chemical: ChemicalRecord,
        model: QsarDBModelRecord,
    ) -> QsarDBPredictionRecord:
        structure = chemical.canonical_smiles or chemical.input_structure
        cached_text = self._read_cached_response(
            structure=structure,
            handle=model.handle,
            model_id=model.model_id,
        )
        if cached_text is not None:
            return self._ok_record(chemical=chemical, model=model, raw_text=cached_text)

        url = self.build_url(
            handle=model.handle,
            model_id=model.model_id,
            structure=structure,
        )

        last_error: str | None = None
        last_response_text: str | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.request_delay_seconds > 0:
                    await asyncio.sleep(self.request_delay_seconds)

                response = await self._get_client().get(url)
                response_text = response.text.strip()
                last_response_text = response_text

                if response.status_code == 200:
                    self._write_cached_response(
                        structure=structure,
                        handle=model.handle,
                        model_id=model.model_id,
                        raw_text=response_text,
                    )
                    try:
                        return self._ok_record(
                        chemical=chemical,
                        model=model,
                        raw_text=response_text,
                        )
                    except Exception as exc:
                        return self._error_record(
                            chemical=chemical, model=model,
                            error=f"Failed to parse response: {exc}",
                            raw_text=response_text
                        )
                last_error = f"HTTP {response.status_code}: {response_text}"
                if response.status_code not in _TRANSIENT_STATUSES:
                    return self._error_record(
                        chemical=chemical,
                        model=model,
                        error=last_error,
                        raw_text=response_text,
                    )
            except httpx.RequestError as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
                last_response_text = None

            if attempt < self.retries and self.retry_delay_seconds > 0:
                await asyncio.sleep(self.retry_delay_seconds)

        return self._error_record(
            chemical=chemical,
            model=model,
            error=last_error or "Prediction request failed",
            raw_text=last_response_text,
        )

    async def predict_many(
        self,
        chemicals: list[ChemicalRecord],
        models: list[QsarDBModelRecord],
    ) -> list[QsarDBPredictionRecord]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def predict_with_limit(
            chemical: ChemicalRecord,
            model: QsarDBModelRecord,
        ) -> QsarDBPredictionRecord:
            async with semaphore:
                return await self.predict_one(chemical, model)

        tasks = [
            predict_with_limit(chemical, model)
            for chemical in chemicals
            for model in models
        ]
        return await asyncio.gather(*tasks)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _ok_record(
        self,
        *,
        chemical: ChemicalRecord,
        model: QsarDBModelRecord,
        raw_text: str,
    ) -> QsarDBPredictionRecord:
        result_name, result_value, result_float = parse_prediction_response(raw_text)
        return QsarDBPredictionRecord(
            compound_id=chemical.compound_id,
            input_structure=chemical.input_structure,
            canonical_smiles=chemical.canonical_smiles,
            handle=model.handle,
            model_id=model.model_id,
            endpoint=model.endpoint,
            model_type=model.model_type,
            prediction_mode=_PREDICTION_MODE,
            status="ok",
            result_name=result_name,
            result_value=result_value,
            result_float=result_float,
            raw_response=raw_text,
            error=None,
        )

    def _error_record(
        self,
        *,
        chemical: ChemicalRecord,
        model: QsarDBModelRecord,
        error: str,
        raw_text: str | None,
    ) -> QsarDBPredictionRecord:
        return QsarDBPredictionRecord(
            compound_id=chemical.compound_id,
            input_structure=chemical.input_structure,
            canonical_smiles=chemical.canonical_smiles,
            handle=model.handle,
            model_id=model.model_id,
            endpoint=model.endpoint,
            model_type=model.model_type,
            prediction_mode=_PREDICTION_MODE,
            status="error",
            raw_response=raw_text,
            error=error,
        )

    def _cache_path(self, *, structure: str, handle: str, model_id: str) -> Path | None:
        if self.cache_dir is None:
            return None

        cache_key = "\n".join([structure, handle, model_id])
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.txt"

    def _read_cached_response(
        self,
        *,
        structure: str,
        handle: str,
        model_id: str,
    ) -> str | None:
        cache_path = self._cache_path(
            structure=structure,
            handle=handle,
            model_id=model_id,
        )
        if cache_path is None or not cache_path.exists():
            return None

        return cache_path.read_text(encoding="utf-8")

    def _write_cached_response(
        self,
        *,
        structure: str,
        handle: str,
        model_id: str,
        raw_text: str,
    ) -> None:
        cache_path = self._cache_path(
            structure=structure,
            handle=handle,
            model_id=model_id,
        )
        if cache_path is None:
            return

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(raw_text, encoding="utf-8")
