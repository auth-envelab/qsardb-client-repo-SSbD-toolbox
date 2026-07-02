"""Parser and fetcher for the QsarDB predictor catalogue page."""

from __future__ import annotations

from html.parser import HTMLParser
import re

import httpx

from qsardb_client.schemas import QsarDBModelRecord


DEFAULT_PREDICTOR_CATALOG_URL = "https://qsardb.org/guidelines/predict"

_HANDLE_PATTERN = re.compile(r"^\d+/\d+$")
_MODEL_SECTION_LABELS = {
    "regression models": "regression",
    "classification models": "classification",
}


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _is_valid_handle(value: str) -> bool:
    return bool(_HANDLE_PATTERN.fullmatch(value))


def _is_valid_model_id(value: str) -> bool:
    normalized = _normalize_text(value)
    return bool(normalized) and normalized.lower() not in {"model", "model id", "model ids"}


def _is_valid_endpoint(value: str) -> bool:
    normalized = _normalize_text(value)
    return bool(normalized) and normalized.lower() != "endpoint"


class _PredictorCatalogHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[QsarDBModelRecord] = []
        self._seen_records: set[tuple[str, str]] = set()
        self._pending_model_type: str | None = None
        self._table_model_type: str | None = None
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._row_cells: list[str] = []
        self._cell_parts: list[str] = []
        self._row_has_header_cell = False
        self._in_row = False
        self._cell_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_tag = tag
            self._heading_parts = []
            return

        if tag == "table":
            self._table_model_type = self._pending_model_type
            return

        if self._table_model_type is None:
            return

        if tag == "tr":
            self._in_row = True
            self._row_cells = []
            self._row_has_header_cell = False
            return

        if self._in_row and tag in {"td", "th"}:
            self._cell_tag = tag
            self._cell_parts = []
            if tag == "th":
                self._row_has_header_cell = True

    def handle_endtag(self, tag: str) -> None:
        if self._heading_tag == tag:
            self._set_pending_model_type()
            self._heading_tag = None
            self._heading_parts = []
            return

        if tag == "table" and self._table_model_type is not None:
            self._table_model_type = None
            self._pending_model_type = None
            return

        if self._table_model_type is None:
            return

        if self._cell_tag == tag:
            self._row_cells.append(_normalize_text("".join(self._cell_parts)))
            self._cell_tag = None
            self._cell_parts = []
            return

        if tag == "tr" and self._in_row:
            self._add_row_record()
            self._in_row = False
            self._row_cells = []
            self._row_has_header_cell = False

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_parts.append(data)

        if self._cell_tag is not None:
            self._cell_parts.append(data)

    def _set_pending_model_type(self) -> None:
        heading = _normalize_text("".join(self._heading_parts)).lower()
        self._pending_model_type = _MODEL_SECTION_LABELS.get(heading)

    def _add_row_record(self) -> None:
        if self._table_model_type is None or self._row_has_header_cell:
            return

        if len(self._row_cells) < 3:
            return

        handle = self._row_cells[0]
        model_id = self._row_cells[1]
        endpoint = self._row_cells[2]

        if not (
            _is_valid_handle(handle)
            and _is_valid_model_id(model_id)
            and _is_valid_endpoint(endpoint)
        ):
            return

        record_key = (handle, model_id)
        if record_key in self._seen_records:
            return

        self._seen_records.add(record_key)
        self.records.append(
            QsarDBModelRecord(
                handle=handle,
                model_id=model_id,
                endpoint=endpoint,
                model_type=self._table_model_type,
            )
        )


def parse_predictor_catalog_html(html: str) -> list[QsarDBModelRecord]:
    parser = _PredictorCatalogHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.records


class PredictorCatalog:
    def __init__(
        self,
        *,
        url: str = DEFAULT_PREDICTOR_CATALOG_URL,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.client = client

    def parse_html(self, html: str) -> list[QsarDBModelRecord]:
        return parse_predictor_catalog_html(html)

    def fetch_html(self) -> str:
        if self.client is not None:
            response = self.client.get(self.url)
            response.raise_for_status()
            return response.text

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(self.url)
            response.raise_for_status()
            return response.text

    def fetch_models(self) -> list[QsarDBModelRecord]:
        return self.parse_html(self.fetch_html())
