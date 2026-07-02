from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from qsardb_client.archive import ParsedQDBArchive, QDBArchiveParser, QDBParseError


def create_synthetic_qdb(path: Path, *, malformed_xml: bool = False) -> Path:
    with ZipFile(path, "w") as zip_file:
        zip_file.writestr(
            "archive.xml",
            '<archive id="A001">Example archive</archive>',
        )
        zip_file.writestr(
            "compounds/C001/compound.xml",
            '<compound id="C001">Compound text</compound>',
        )
        zip_file.writestr("compounds/C001/daylight-smiles", "CCO")
        zip_file.writestr(
            "properties/P001/property.xml",
            '<property id="P001">Property text</property>',
        )
        zip_file.writestr("properties/P001/values", "C001\t1.0\n")
        zip_file.writestr(
            "descriptors/D001/descriptor.xml",
            '<descriptor id="D001">Descriptor text</descriptor>',
        )
        zip_file.writestr(
            "models/M001/model.xml",
            '<model id="M001">Model text</model>',
        )
        zip_file.writestr(
            "predictions/PR001/prediction.xml",
            '<prediction id="PR001">Prediction text</prediction>',
        )
        zip_file.writestr("predictions/PR001/values", "C001\t13.8\n")
        zip_file.writestr("unrelated/readme.txt", "ignored")
        if malformed_xml:
            zip_file.writestr("compounds/C002/compound.xml", "<compound>")
    return path


def test_parse_validates_missing_file_path(tmp_path: Path) -> None:
    with pytest.raises(QDBParseError, match="does not exist"):
        QDBArchiveParser().parse(tmp_path / "missing.qdb")


def test_parse_validates_non_zip_file(tmp_path: Path) -> None:
    path = tmp_path / "not-a-zip.qdb"
    path.write_text("not zip", encoding="utf-8")

    with pytest.raises(QDBParseError, match="not a ZIP"):
        QDBArchiveParser().parse(path)


def test_parse_returns_entries_table(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    parsed = QDBArchiveParser().parse(path)

    assert isinstance(parsed, ParsedQDBArchive)
    entries = parsed.tables["entries"]
    assert set(entries.columns) == {"path", "is_dir", "size"}
    assert "archive.xml" in set(entries["path"])
    assert "compounds/C001/compound.xml" in parsed.entries


def test_parse_detects_standard_containers(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    parsed = QDBArchiveParser().parse(path)

    assert set(parsed.tables["containers"]["container"]) == {
        "compounds",
        "properties",
        "descriptors",
        "models",
        "predictions",
    }


def test_parse_counts_container_items(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    containers = QDBArchiveParser().parse(path).tables["containers"]
    counts = dict(zip(containers["container"], containers["item_count"]))

    assert counts == {
        "compounds": 1,
        "properties": 1,
        "descriptors": 1,
        "models": 1,
        "predictions": 1,
    }


def test_parse_reads_archive_xml_shallow_metadata(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    parsed = QDBArchiveParser().parse(path)

    assert parsed.archive_metadata == {
        "xml_path": "archive.xml",
        "root_tag": "archive",
        "attributes": {"id": "A001"},
        "text": "Example archive",
    }
    assert parsed.tables["archive_metadata"].loc[0, "root_tag"] == "archive"


def test_parse_reads_container_xml_files_into_xml_files_table(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    xml_files = QDBArchiveParser().parse(path).tables["xml_files"]

    assert set(xml_files["container"]) == {
        "compounds",
        "properties",
        "descriptors",
        "models",
        "predictions",
    }
    compound_row = xml_files[xml_files["xml_path"] == "compounds/C001/compound.xml"].iloc[0]
    assert compound_row["item_id"] == "C001"
    assert compound_row["root_tag"] == "compound"
    assert compound_row["attributes"] == {"id": "C001"}
    assert compound_row["text"] == "Compound text"
    assert compound_row["parse_error"] is None


def test_parse_records_cargos_without_parsing_contents(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    cargos = QDBArchiveParser().parse(path).tables["cargos"]

    assert set(cargos["cargo_path"]) == {
        "compounds/C001/daylight-smiles",
        "properties/P001/values",
        "predictions/PR001/values",
    }
    smiles = cargos[cargos["cargo_path"] == "compounds/C001/daylight-smiles"].iloc[0]
    assert smiles["cargo_name"] == "daylight-smiles"
    assert smiles["size"] == 3


def test_parse_ignores_unrecognized_top_level_folders_for_containers(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    parsed = QDBArchiveParser().parse(path)

    assert "unrelated" not in parsed.containers
    assert "unrelated" not in set(parsed.tables["containers"]["container"])


def test_malformed_xml_under_container_is_recorded_not_crashing(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb", malformed_xml=True)

    xml_files = QDBArchiveParser().parse(path).tables["xml_files"]
    malformed = xml_files[xml_files["xml_path"] == "compounds/C002/compound.xml"].iloc[0]

    assert malformed["container"] == "compounds"
    assert malformed["item_id"] == "C002"
    assert malformed["root_tag"] is None
    assert malformed["attributes"] == {}
    assert isinstance(malformed["parse_error"], str)
    assert malformed["parse_error"]


def test_parsed_archive_containers_contains_present_recognized_keys(tmp_path: Path) -> None:
    path = create_synthetic_qdb(tmp_path / "archive.qdb")

    containers = QDBArchiveParser().parse(path).containers

    assert set(containers) == {
        "compounds",
        "properties",
        "descriptors",
        "models",
        "predictions",
    }
    assert containers["compounds"][0]["xml_path"] == "compounds/C001/compound.xml"
