"""Minimal OAI-PMH metadata client and parser."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

import httpx


DEFAULT_OAI_BASE_URL = "https://qsardb.org/oai/request"
DEFAULT_MAX_PAGES = 10


class OAIPMHError(Exception):
    """Base exception for OAI-PMH client and parser failures."""


@dataclass(frozen=True)
class OAIMetadataRecord:
    identifier: str
    datestamp: str | None
    set_specs: tuple[str, ...]
    metadata_prefix: str | None
    metadata: dict[str, Any]
    raw_xml: str


def parse_oai_response(
    xml_text: str,
    *,
    metadata_prefix: str | None = None,
) -> dict[str, Any]:
    """Parse an OAI-PMH XML response into JSON-friendly metadata."""

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise OAIPMHError(f"Malformed OAI-PMH XML: {exc}") from exc

    request_element = _first_child(root, "request")
    request_attributes = _attributes(request_element) if request_element is not None else {}
    request_metadata_prefix = request_attributes.get("metadataPrefix")
    effective_metadata_prefix = metadata_prefix or request_metadata_prefix

    result: dict[str, Any] = {
        "response_date": _child_text(root, "responseDate"),
        "request": _request_payload(request_element),
        "verb": request_attributes.get("verb") or _infer_verb(root),
        "errors": _error_payloads(root),
        "records": [],
        "resumption_token": None,
        "metadata_formats": [],
        "sets": [],
        "raw_root_tag": _local_tag(root.tag),
    }

    identify = _first_child(root, "Identify")
    if identify is not None:
        result["identify"] = _children_to_dict(identify)

    list_metadata_formats = _first_child(root, "ListMetadataFormats")
    if list_metadata_formats is not None:
        result["metadata_formats"] = [
            _children_to_dict(child)
            for child in list(list_metadata_formats)
            if _local_tag(child.tag) == "metadataFormat"
        ]

    list_sets = _first_child(root, "ListSets")
    if list_sets is not None:
        result["sets"] = [
            _children_to_dict(child)
            for child in list(list_sets)
            if _local_tag(child.tag) == "set"
        ]
        result["resumption_token"] = _resumption_token(list_sets)

    for parent_name in ["ListRecords", "GetRecord"]:
        parent = _first_child(root, parent_name)
        if parent is None:
            continue
        result["records"].extend(
            _record_payload(record, effective_metadata_prefix)
            for record in list(parent)
            if _local_tag(record.tag) == "record"
        )
        token = _resumption_token(parent)
        if token:
            result["resumption_token"] = token

    return result


class OAIPMHClient:
    """Small OAI-PMH client for public repository metadata."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OAI_BASE_URL,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.Client | None = None,
        max_pages: int | None = DEFAULT_MAX_PAGES,
    ) -> None:
        self.base_url = base_url
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._default_max_pages = max_pages

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OAIPMHClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def request(self, **params: str) -> dict[str, Any]:
        response = self._client.get(self.base_url, params=params)
        status_code = getattr(response, "status_code", None)
        if status_code is not None and int(status_code) >= 400:
            raise OAIPMHError(f"OAI-PMH request failed with HTTP status {status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OAIPMHError(f"OAI-PMH request failed: {exc}") from exc
        return parse_oai_response(
            response.text,
            metadata_prefix=params.get("metadataPrefix"),
        )

    def identify(self) -> dict[str, Any]:
        return self.request(verb="Identify")

    def list_metadata_formats(self) -> dict[str, Any]:
        return self.request(verb="ListMetadataFormats")

    def list_sets(self) -> dict[str, Any]:
        return self.request(verb="ListSets")

    def list_records(
        self,
        *,
        metadata_prefix: str = "oai_dc",
        from_: str | None = None,
        until: str | None = None,
        set_: str | None = None,
        max_pages: int | None = None,
    ) -> list[OAIMetadataRecord]:
        page_limit = self._default_max_pages if max_pages is None else max_pages
        if page_limit is not None and page_limit <= 0:
            return []

        params = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
        if from_:
            params["from"] = from_
        if until:
            params["until"] = until
        if set_:
            params["set"] = set_

        records: list[OAIMetadataRecord] = []
        page_count = 0
        while True:
            parsed = self.request(**params)
            page_records = [
                _record_from_payload(
                    {
                        **record,
                        "metadata_prefix": record.get("metadata_prefix") or metadata_prefix,
                    }
                )
                for record in parsed["records"]
            ]
            records.extend(page_records)

            if parsed["errors"] and not page_records:
                raise OAIPMHError(_format_oai_errors(parsed["errors"]))

            page_count += 1
            token = parsed.get("resumption_token")
            if not token:
                break
            if page_limit is not None and page_count >= page_limit:
                break
            params = {"verb": "ListRecords", "resumptionToken": str(token)}
        return records

    def get_record(
        self,
        *,
        identifier: str,
        metadata_prefix: str = "oai_dc",
    ) -> OAIMetadataRecord | None:
        parsed = self.request(
            verb="GetRecord",
            identifier=identifier,
            metadataPrefix=metadata_prefix,
        )
        records = [_record_from_payload(record) for record in parsed["records"]]
        if parsed["errors"] and not records:
            raise OAIPMHError(_format_oai_errors(parsed["errors"]))
        return records[0] if records else None


def _record_payload(
    record_element: ElementTree.Element,
    metadata_prefix: str | None,
) -> dict[str, Any]:
    header = _first_child(record_element, "header")
    metadata_element = _first_child(record_element, "metadata")
    metadata = _metadata_payload(metadata_element)
    return {
        "identifier": _child_text(header, "identifier") if header is not None else "",
        "datestamp": _child_text(header, "datestamp") if header is not None else None,
        "set_specs": [
            _clean_text(child.text)
            for child in list(header or [])
            if _local_tag(child.tag) == "setSpec" and _clean_text(child.text)
        ],
        "metadata_prefix": metadata_prefix,
        "metadata": metadata,
        "raw_xml": ElementTree.tostring(record_element, encoding="unicode"),
    }


def _record_from_payload(payload: dict[str, Any]) -> OAIMetadataRecord:
    return OAIMetadataRecord(
        identifier=str(payload.get("identifier") or ""),
        datestamp=payload.get("datestamp"),
        set_specs=tuple(str(value) for value in payload.get("set_specs", [])),
        metadata_prefix=payload.get("metadata_prefix"),
        metadata=dict(payload.get("metadata") or {}),
        raw_xml=str(payload.get("raw_xml") or ""),
    )


def _metadata_payload(metadata_element: ElementTree.Element | None) -> dict[str, Any]:
    if metadata_element is None:
        return {}
    children = list(metadata_element)
    if not children:
        return {}
    if len(children) == 1:
        metadata_root = children[0]
        payload = _children_to_dict(metadata_root)
        payload["_metadata_root"] = _local_tag(metadata_root.tag)
        return payload

    payload = {}
    for child in children:
        _add_repeated(payload, _local_tag(child.tag), _element_to_json(child))
    return payload


def _request_payload(request_element: ElementTree.Element | None) -> dict[str, Any] | None:
    if request_element is None:
        return None
    return {
        "text": _clean_text(request_element.text),
        "attributes": _attributes(request_element),
    }


def _error_payloads(root: ElementTree.Element) -> list[dict[str, str]]:
    errors = []
    for child in list(root):
        if _local_tag(child.tag) == "error":
            errors.append(
                {
                    "code": _clean_text(child.attrib.get("code")),
                    "message": _clean_text(child.text),
                }
            )
    return errors


def _resumption_token(parent: ElementTree.Element) -> str | None:
    element = _first_child(parent, "resumptionToken")
    if element is None:
        return None
    return _clean_text(element.text) or None


def _children_to_dict(element: ElementTree.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in list(element):
        _add_repeated(result, _local_tag(child.tag), _element_to_json(child))
    return result


def _element_to_json(element: ElementTree.Element) -> Any:
    children = list(element)
    attributes = _attributes(element)
    text = _clean_text(element.text)
    if not children:
        if attributes:
            payload: dict[str, Any] = {"attributes": attributes}
            if text:
                payload["text"] = text
            return payload
        return text

    payload = _children_to_dict(element)
    if attributes:
        payload["@attributes"] = attributes
    if text:
        payload["text"] = text
    return payload


def _add_repeated(payload: dict[str, Any], key: str, value: Any) -> None:
    if key in payload:
        existing = payload[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            payload[key] = [existing, value]
    else:
        payload[key] = value


def _attributes(element: ElementTree.Element | None) -> dict[str, str]:
    if element is None:
        return {}
    return {_local_tag(key): str(value) for key, value in element.attrib.items()}


def _first_child(
    element: ElementTree.Element | None,
    child_name: str,
) -> ElementTree.Element | None:
    if element is None:
        return None
    for child in list(element):
        if _local_tag(child.tag) == child_name:
            return child
    return None


def _child_text(element: ElementTree.Element | None, child_name: str) -> str | None:
    child = _first_child(element, child_name)
    if child is None:
        return None
    text = _clean_text(child.text)
    return text or None


def _infer_verb(root: ElementTree.Element) -> str | None:
    known_verbs = {
        "Identify",
        "ListMetadataFormats",
        "ListSets",
        "ListRecords",
        "GetRecord",
    }
    for child in list(root):
        tag = _local_tag(child.tag)
        if tag in known_verbs:
            return tag
    return None


def _format_oai_errors(errors: Iterable[dict[str, str]]) -> str:
    return "; ".join(
        f"{error.get('code')}: {error.get('message')}".strip(": ")
        for error in errors
    )


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()
