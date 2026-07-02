from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from zipfile import ZipFile

from qsardb_client.archive import QDBArchiveParser
from qsardb_client.cli import main
from qsardb_client.export import records_to_json
from qsardb_client.predictor import parse_predictor_catalog_html
from qsardb_client.schemas import ChemicalRecord, QsarDBModelRecord, QsarDBPredictionRecord


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def test_readme_states_package_is_not_ssbd_scoring_layer() -> None:
    text = readme_text()

    assert "QsarDB-native Python integration layer" in text
    assert "not an SSbD scoring layer" in text
    assert "safe/unsafe decisions" in text


def test_readme_mentions_accepted_capabilities() -> None:
    text = readme_text()

    for phrase in [
        "typed schemas",
        "predictor catalogue parsing",
        "remote predictor client",
        "optional chemistry normalization",
        "neutral export utilities",
        "CLI for catalogue refresh and remote prediction",
        "direct archive download from a caller-supplied URL",
        "local QDB ZIP structural parser skeleton",
    ]:
        assert phrase in text


def test_readme_does_not_document_unsupported_archive_cli_commands() -> None:
    text = readme_text().lower()

    assert "qsardb-client archive" not in text
    assert "qsardb-client repository" not in text
    assert "qsardb-client ssbd" not in text


def test_readme_python_code_blocks_compile() -> None:
    text = readme_text()
    code_blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)

    assert code_blocks
    for code_block in code_blocks:
        compile(code_block, "README.md", "exec")


def test_local_static_html_catalogue_example_can_be_parsed() -> None:
    html = """
    <h4>Regression models</h4>
    <table>
      <tr><th>Handle</th><th>Model IDs</th><th>Endpoint</th></tr>
      <tr><td>10967/257</td><td>M1</td><td>Intrinsic aqueous solubility</td></tr>
    </table>
    """

    models = parse_predictor_catalog_html(html)

    assert len(models) == 1
    assert models[0].handle == "10967/257"
    assert models[0].model_id == "M1"


class FakeRemotePredictorClient:
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


def test_fake_remote_prediction_example_can_be_exported_without_live_network(
    tmp_path: Path,
) -> None:
    chemicals = [ChemicalRecord(compound_id="compound-1", input_structure="CCO")]
    models = [
        QsarDBModelRecord(
            handle="10967/257",
            model_id="M1",
            endpoint="Intrinsic aqueous solubility",
            model_type="regression",
        )
    ]

    predictions = asyncio.run(FakeRemotePredictorClient().predict_many(chemicals, models))
    output_path = records_to_json(predictions, tmp_path / "predictions.json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload[0]["compound_id"] == "compound-1"
    assert payload[0]["raw_response"] == "mpC = 13.8"


def test_synthetic_local_qdb_zip_can_be_parsed(tmp_path: Path) -> None:
    archive_path = tmp_path / "example.qdb"
    with ZipFile(archive_path, "w") as zip_file:
        zip_file.writestr("archive.xml", '<archive id="A001">Example</archive>')
        zip_file.writestr("compounds/C001/compound.xml", '<compound id="C001" />')

    parsed = QDBArchiveParser().parse(archive_path)

    assert parsed.archive_metadata["root_tag"] == "archive"
    assert "compounds" in parsed.containers
    assert "compounds/C001/compound.xml" in set(parsed.tables["entries"]["path"])


def test_cli_help_can_be_invoked_without_live_network(capsys) -> None:
    assert main(["--help"]) == 0
    assert "catalog" in capsys.readouterr().out
