from __future__ import annotations

import json

from qsardb_client.predictor import PredictorCatalog, parse_predictor_catalog_html
from qsardb_client.schemas import QsarDBModelRecord


CATALOG_HTML = """
<html>
  <body>
    <h4>Regression models</h4>
    <table>
      <thead>
        <tr>
          <th>Handle</th>
          <th>Model IDs</th>
          <th>Endpoint</th>
          <th>Example request URL</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><a href="/repository/handle/10967/257">10967/257</a></td>
          <td><a href="/repository/model/M1">M1</a></td>
          <td>Intrinsic aqueous solubility</td>
          <td>Copy</td>
        </tr>
        <tr>
          <td>10967/257</td>
          <td>M1</td>
          <td>Duplicate should be ignored</td>
          <td>Copy</td>
        </tr>
        <tr>
          <td>not-a-handle</td>
          <td>BrokenModel</td>
          <td>Malformed handle should be ignored</td>
          <td>Copy</td>
        </tr>
      </tbody>
    </table>

    <h4>Classification models</h4>
    <table>
      <tbody>
        <tr>
          <th>Handle</th>
          <th>Model IDs</th>
          <th>Endpoint</th>
          <th>Example request URL</th>
        </tr>
        <tr>
          <td>10967/259</td>
          <td>Tab3.agonists</td>
          <td>Activity in ER agonist pathway</td>
          <td>Copy</td>
        </tr>
        <tr>
          <td>10967/999</td>
          <td></td>
          <td>Missing model should be ignored</td>
          <td>Copy</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.raise_for_status_called = False

    def raise_for_status(self) -> None:
        self.raise_for_status_called = True


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requested_urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested_urls.append(url)
        return self.response


def assert_serializable(record: QsarDBModelRecord) -> None:
    data = record.model_dump(mode="json")
    json.dumps(data)
    assert json.loads(record.model_dump_json()) == data


def test_parse_predictor_catalog_html_extracts_regression_and_classification_models() -> None:
    records = parse_predictor_catalog_html(CATALOG_HTML)

    assert len(records) == 2
    assert all(isinstance(record, QsarDBModelRecord) for record in records)

    regression = records[0]
    assert regression.handle == "10967/257"
    assert regression.model_id == "M1"
    assert regression.endpoint == "Intrinsic aqueous solubility"
    assert regression.model_type == "regression"
    assert_serializable(regression)

    classification = records[1]
    assert classification.handle == "10967/259"
    assert classification.model_id == "Tab3.agonists"
    assert classification.endpoint == "Activity in ER agonist pathway"
    assert classification.model_type == "classification"
    assert_serializable(classification)


def test_parse_predictor_catalog_html_deduplicates_and_ignores_malformed_rows() -> None:
    records = parse_predictor_catalog_html(CATALOG_HTML)
    keys = [(record.handle, record.model_id) for record in records]

    assert keys == [("10967/257", "M1"), ("10967/259", "Tab3.agonists")]
    assert all(record.handle != "not-a-handle" for record in records)
    assert all(record.model_id for record in records)


def test_predictor_catalog_parse_html_delegates_to_parser() -> None:
    catalog = PredictorCatalog(url="https://example.invalid/catalog")

    records = catalog.parse_html(CATALOG_HTML)

    assert [record.model_type for record in records] == ["regression", "classification"]


def test_fetch_models_uses_injected_client_and_parses_returned_html() -> None:
    response = FakeResponse(CATALOG_HTML)
    client = FakeClient(response)
    catalog = PredictorCatalog(url="https://example.invalid/catalog", client=client)

    records = catalog.fetch_models()

    assert client.requested_urls == ["https://example.invalid/catalog"]
    assert response.raise_for_status_called is True
    assert [(record.handle, record.model_id) for record in records] == [
        ("10967/257", "M1"),
        ("10967/259", "Tab3.agonists"),
    ]
