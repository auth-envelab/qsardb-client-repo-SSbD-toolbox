from __future__ import annotations

import socket

import httpx
import pytest

from qsardb_client.repository import (
    OAIMetadataRecord,
    OAIPMHClient,
    OAIPMHError,
    parse_oai_response,
)


IDENTIFY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="Identify">https://example.invalid/oai</request>
  <Identify>
    <repositoryName>QsarDB</repositoryName>
    <baseURL>https://example.invalid/oai</baseURL>
    <protocolVersion>2.0</protocolVersion>
  </Identify>
</OAI-PMH>
"""

METADATA_FORMATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="ListMetadataFormats">https://example.invalid/oai</request>
  <ListMetadataFormats>
    <metadataFormat>
      <metadataPrefix>oai_dc</metadataPrefix>
      <schema>http://www.openarchives.org/OAI/2.0/oai_dc.xsd</schema>
      <metadataNamespace>http://www.openarchives.org/OAI/2.0/oai_dc/</metadataNamespace>
    </metadataFormat>
  </ListMetadataFormats>
</OAI-PMH>
"""

SETS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="ListSets">https://example.invalid/oai</request>
  <ListSets>
    <set>
      <setSpec>archive</setSpec>
      <setName>Archives</setName>
    </set>
  </ListSets>
</OAI-PMH>
"""

LIST_RECORDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="ListRecords" metadataPrefix="oai_dc">https://example.invalid/oai</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:qsardb:1</identifier>
        <datestamp>2026-01-01</datestamp>
        <setSpec>archive</setSpec>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title>First archive</dc:title>
          <dc:title>First archive subtitle</dc:title>
          <dc:creator>Alice</dc:creator>
          <dc:creator>Bob</dc:creator>
          <dc:identifier>https://doi.org/10.1234/example.1</dc:identifier>
          <dc:identifier>hdl:10967/1</dc:identifier>
          <dc:identifier>https://example.invalid/files/archive.qdb</dc:identifier>
        </oai_dc:dc>
      </metadata>
    </record>
    <record>
      <header>
        <identifier>oai:qsardb:2</identifier>
        <datestamp>2026-01-02</datestamp>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title>Second archive</dc:title>
          <dc:identifier>https://example.invalid/docs/qmrf.pdf</dc:identifier>
        </oai_dc:dc>
      </metadata>
    </record>
    <resumptionToken>token-2</resumptionToken>
  </ListRecords>
</OAI-PMH>
"""

LIST_RECORDS_PAGE_2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="ListRecords" resumptionToken="token-2">https://example.invalid/oai</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:qsardb:3</identifier>
        <datestamp>2026-01-03</datestamp>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title>Third archive</dc:title>
        </oai_dc:dc>
      </metadata>
    </record>
  </ListRecords>
</OAI-PMH>
"""

GET_RECORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="GetRecord" identifier="oai:qsardb:1" metadataPrefix="oai_dc">https://example.invalid/oai</request>
  <GetRecord>
    <record>
      <header>
        <identifier>oai:qsardb:1</identifier>
        <datestamp>2026-01-01</datestamp>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title>First archive</dc:title>
        </oai_dc:dc>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>
"""

ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-07-01T00:00:00Z</responseDate>
  <request verb="ListRecords">https://example.invalid/oai</request>
  <error code="noRecordsMatch">No records match</error>
</OAI-PMH>
"""


def test_parse_identify_response() -> None:
    parsed = parse_oai_response(IDENTIFY_XML)

    assert parsed["verb"] == "Identify"
    assert parsed["identify"]["repositoryName"] == "QsarDB"
    assert parsed["request"]["attributes"]["verb"] == "Identify"


def test_parse_list_metadata_formats_response() -> None:
    parsed = parse_oai_response(METADATA_FORMATS_XML)

    assert parsed["metadata_formats"][0]["metadataPrefix"] == "oai_dc"
    assert parsed["metadata_formats"][0]["schema"].endswith("oai_dc.xsd")


def test_parse_list_sets_response() -> None:
    parsed = parse_oai_response(SETS_XML)

    assert parsed["sets"] == [{"setSpec": "archive", "setName": "Archives"}]


def test_parse_list_records_response_with_repeated_dublin_core_fields() -> None:
    parsed = parse_oai_response(LIST_RECORDS_XML, metadata_prefix="oai_dc")

    assert parsed["verb"] == "ListRecords"
    assert parsed["resumption_token"] == "token-2"
    assert len(parsed["records"]) == 2
    first = parsed["records"][0]
    assert first["identifier"] == "oai:qsardb:1"
    assert first["set_specs"] == ["archive"]
    assert first["metadata_prefix"] == "oai_dc"
    assert first["metadata"]["_metadata_root"] == "dc"
    assert first["metadata"]["title"] == ["First archive", "First archive subtitle"]
    assert first["metadata"]["creator"] == ["Alice", "Bob"]


def test_parse_get_record_response() -> None:
    parsed = parse_oai_response(GET_RECORD_XML, metadata_prefix="oai_dc")

    assert parsed["verb"] == "GetRecord"
    assert parsed["records"][0]["identifier"] == "oai:qsardb:1"
    assert parsed["records"][0]["metadata"]["title"] == "First archive"


def test_parse_oai_error_response_preserves_errors() -> None:
    parsed = parse_oai_response(ERROR_XML)

    assert parsed["errors"] == [{"code": "noRecordsMatch", "message": "No records match"}]
    assert parsed["records"] == []


def test_malformed_xml_raises_oai_error() -> None:
    with pytest.raises(OAIPMHError):
        parse_oai_response("<OAI-PMH><broken></OAI-PMH>")


def test_namespace_handling_uses_local_tag_names() -> None:
    parsed = parse_oai_response(LIST_RECORDS_XML, metadata_prefix="oai_dc")

    assert parsed["raw_root_tag"] == "OAI-PMH"
    assert "title" in parsed["records"][0]["metadata"]


def _client_for_handler(handler) -> OAIPMHClient:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    return OAIPMHClient(
        base_url="https://example.invalid/oai",
        client=httpx.Client(transport=transport),
    )


def test_client_identify_uses_identify_verb() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=IDENTIFY_XML)

    client = _client_for_handler(handler)

    parsed = client.identify()

    assert parsed["verb"] == "Identify"
    assert requests[0].url.params["verb"] == "Identify"


def test_client_list_metadata_formats_uses_list_metadata_formats_verb() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=METADATA_FORMATS_XML)

    client = _client_for_handler(handler)

    parsed = client.list_metadata_formats()

    assert parsed["metadata_formats"][0]["metadataPrefix"] == "oai_dc"
    assert requests[0].url.params["verb"] == "ListMetadataFormats"


def test_client_list_sets_uses_list_sets_verb() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=SETS_XML)

    client = _client_for_handler(handler)

    parsed = client.list_sets()

    assert parsed["sets"][0]["setSpec"] == "archive"
    assert requests[0].url.params["verb"] == "ListSets"


def test_client_list_records_parses_records_from_mocked_xml() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=LIST_RECORDS_XML.replace("<resumptionToken>token-2</resumptionToken>", ""))

    client = _client_for_handler(handler)

    records = client.list_records(metadata_prefix="oai_dc")

    assert len(records) == 2
    assert all(isinstance(record, OAIMetadataRecord) for record in records)
    assert records[0].identifier == "oai:qsardb:1"


def test_client_list_records_follows_resumption_token() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "resumptionToken=token-2" in str(request.url):
            return httpx.Response(200, text=LIST_RECORDS_PAGE_2_XML)
        return httpx.Response(200, text=LIST_RECORDS_XML)

    client = _client_for_handler(handler)

    records = client.list_records(metadata_prefix="oai_dc")

    assert [record.identifier for record in records] == [
        "oai:qsardb:1",
        "oai:qsardb:2",
        "oai:qsardb:3",
    ]
    assert requests[0].url.params["metadataPrefix"] == "oai_dc"
    assert requests[1].url.params["resumptionToken"] == "token-2"
    assert "metadataPrefix" not in requests[1].url.params


def test_client_list_records_respects_max_pages() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=LIST_RECORDS_XML)

    client = _client_for_handler(handler)

    records = client.list_records(metadata_prefix="oai_dc", max_pages=1)

    assert len(records) == 2
    assert len(requests) == 1


def test_client_get_record_returns_one_record() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=GET_RECORD_XML)

    client = _client_for_handler(handler)

    record = client.get_record(identifier="oai:qsardb:1", metadata_prefix="oai_dc")

    assert record is not None
    assert record.identifier == "oai:qsardb:1"
    assert requests[0].url.params["verb"] == "GetRecord"
    assert requests[0].url.params["identifier"] == "oai:qsardb:1"


def test_http_500_raises_oai_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = _client_for_handler(handler)

    with pytest.raises(OAIPMHError):
        client.identify()


def test_client_tests_do_not_use_live_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("live network access was attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    client = _client_for_handler(lambda request: httpx.Response(200, text=IDENTIFY_XML))

    assert client.identify()["verb"] == "Identify"
