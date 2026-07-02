from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from qsardb_client.archive import (
    CargoParseError,
    QDBArchiveParser,
    make_cargo_error_record,
    parse_references_tsv,
    parse_two_column_tsv,
    read_text_cargo,
)


def test_read_text_cargo_decodes_utf8_text() -> None:
    assert read_text_cargo("alpha\nbeta\n".encode("utf-8")) == "alpha\nbeta"


def test_read_text_cargo_falls_back_to_latin1() -> None:
    assert read_text_cargo(b"caf\xe9") == "caf" + chr(233)


def test_parse_two_column_tsv_parses_no_header_tsv() -> None:
    result = parse_two_column_tsv(
        "C001\t13.8\nC002\t14.2\n",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result[["compound_id", "value"]].to_dict("records") == [
        {"compound_id": "C001", "value": "13.8"},
        {"compound_id": "C002", "value": "14.2"},
    ]
    assert result["source_path"].unique().tolist() == ["properties/P001/values"]


def test_parse_two_column_tsv_parses_header_tsv() -> None:
    result = parse_two_column_tsv(
        "compound_id\tvalue\nC001\t13.8\n",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result.to_dict("records") == [
        {
            "compound_id": "C001",
            "value": "13.8",
            "source_path": "properties/P001/values",
        }
    ]


def test_parse_two_column_tsv_preserves_duplicate_compound_rows() -> None:
    result = parse_two_column_tsv(
        "C001\t13.8\nC001\t14.2\n",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result["compound_id"].tolist() == ["C001", "C001"]
    assert result["value"].tolist() == ["13.8", "14.2"]


def test_parse_two_column_tsv_preserves_values_as_strings() -> None:
    result = parse_two_column_tsv(
        "C001\t001.230\n",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result.loc[0, "value"] == "001.230"


def test_parse_two_column_tsv_handles_additional_columns() -> None:
    result = parse_two_column_tsv(
        "C001\t13.8\tmeasured\n",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result.loc[0, "extra_1"] == "measured"


def test_parse_two_column_tsv_handles_empty_text() -> None:
    result = parse_two_column_tsv(
        "",
        value_column_name="value",
        source_path="properties/P001/values",
    )

    assert result.empty
    assert list(result.columns) == ["compound_id", "value", "source_path"]


def test_parse_two_column_tsv_raises_for_malformed_rows() -> None:
    try:
        parse_two_column_tsv(
            "C001-only\n",
            value_column_name="value",
            source_path="properties/P001/values",
        )
    except CargoParseError as exc:
        assert "fewer than 2 columns" in str(exc)
    else:
        raise AssertionError("CargoParseError was not raised")


def test_parse_references_tsv_parses_reference_rows() -> None:
    result = parse_references_tsv(
        "compound_id\treference_id\nC001\tR001\n",
        source_path="properties/P001/references",
    )

    assert result[["compound_id", "reference_id"]].to_dict("records") == [
        {"compound_id": "C001", "reference_id": "R001"}
    ]


def test_make_cargo_error_record_returns_json_friendly_fields() -> None:
    assert make_cargo_error_record(
        container="properties",
        item_id="P001",
        cargo_path="properties/P001/values",
        cargo_name="values",
        error="bad row",
    ) == {
        "container": "properties",
        "item_id": "P001",
        "cargo_path": "properties/P001/values",
        "cargo_name": "values",
        "error": "bad row",
    }


def _create_qdb_with_cargos(path: Path) -> Path:
    with ZipFile(path, "w") as zip_file:
        zip_file.writestr("archive.xml", '<archive id="A001">Archive text</archive>')
        zip_file.writestr("compounds/C001/compound.xml", '<compound id="C001" />')
        zip_file.writestr("compounds/C001/daylight-smiles", " CCO \n")
        zip_file.writestr("compounds/C001/mdl-molfile", "mol line 1\nmol line 2\n")
        zip_file.writestr("compounds/C001/bibtex", "@article{compound, title={Compound}}\n")
        zip_file.writestr("properties/P001/property.xml", '<property id="P001" />')
        zip_file.writestr(
            "properties/P001/values",
            "compound_id\tvalue\tflag\nC001\t1.0\tA\nC001\t2.0\tB\n",
        )
        zip_file.writestr("properties/P001/ucum", "mg/L\n")
        zip_file.writestr("properties/P001/references", "C001\tR-PROP\n")
        zip_file.writestr("properties/P001/bibtex", "@article{prop, title={Property}}\n")
        zip_file.writestr("properties/P001/notes", "unrecognized cargo")
        zip_file.writestr("properties/P_BAD/property.xml", '<property id="P_BAD" />')
        zip_file.writestr("properties/P_BAD/values", "C001-only\n")
        zip_file.writestr("descriptors/D001/descriptor.xml", '<descriptor id="D001" />')
        zip_file.writestr("descriptors/D001/values", "C001\tD-1\nC002\tD-2\n")
        zip_file.writestr("descriptors/D001/ucum", "1\n")
        zip_file.writestr("descriptors/D001/references", "compound_id\treference_id\nC001\tR-DESC\n")
        zip_file.writestr("descriptors/D001/bibtex", "@article{desc, title={Descriptor}}\n")
        zip_file.writestr("models/M001/model.xml", '<model id="M001" />')
        zip_file.writestr("models/M001/pmml", "<PMML><Header /></PMML>\n")
        zip_file.writestr("models/M001/bibtex", "@article{model, title={Model}}\n")
        zip_file.writestr("predictions/PR001/prediction.xml", '<prediction id="PR001" />')
        zip_file.writestr("predictions/PR001/values", "C001\tP-1\n")
        zip_file.writestr("predictions/PR001/ucum", "class\n")
        zip_file.writestr("predictions/PR001/references", "C001\tR-PRED\n")
        zip_file.writestr("predictions/PR001/bibtex", "@article{pred, title={Prediction}}\n")
        zip_file.writestr("unrelated/readme.txt", "ignored top level")
    return path


def test_qdb_parser_extracts_neutral_cargo_tables(tmp_path: Path) -> None:
    parsed = QDBArchiveParser().parse(_create_qdb_with_cargos(tmp_path / "archive.qdb"))

    for table_name in [
        "entries",
        "archive_metadata",
        "containers",
        "xml_files",
        "cargos",
    ]:
        assert table_name in parsed.tables

    for table_name in [
        "compound_structures",
        "property_values",
        "descriptor_values",
        "prediction_values",
        "ucum_units",
        "references",
        "bibtex_entries",
        "model_pmml_files",
        "cargo_parse_errors",
    ]:
        assert table_name in parsed.tables

    structures = parsed.tables["compound_structures"]
    assert set(structures["structure_format"]) == {"smiles", "mdl-molfile"}
    assert structures.loc[structures["structure_format"].eq("smiles"), "structure_text"].item() == " CCO "
    assert "mol line 1\nmol line 2" in structures["structure_text"].tolist()

    property_values = parsed.tables["property_values"]
    assert property_values["compound_id"].tolist() == ["C001", "C001"]
    assert property_values["value"].tolist() == ["1.0", "2.0"]
    assert property_values["flag"].tolist() == ["A", "B"]

    descriptor_values = parsed.tables["descriptor_values"]
    assert descriptor_values[["compound_id", "value"]].to_dict("records") == [
        {"compound_id": "C001", "value": "D-1"},
        {"compound_id": "C002", "value": "D-2"},
    ]

    prediction_values = parsed.tables["prediction_values"]
    assert prediction_values[["compound_id", "value"]].to_dict("records") == [
        {"compound_id": "C001", "value": "P-1"}
    ]

    ucum_units = parsed.tables["ucum_units"]
    assert set(ucum_units["unit_text"]) == {"mg/L", "1", "class"}

    references = parsed.tables["references"]
    assert set(references["reference_id"]) == {"R-PROP", "R-DESC", "R-PRED"}

    bibtex_entries = parsed.tables["bibtex_entries"]
    assert len(bibtex_entries) == 5
    assert any("@article{model" in text for text in bibtex_entries["bibtex_text"])

    pmml = parsed.tables["model_pmml_files"]
    assert pmml.loc[0, "pmml_text"] == "<PMML><Header /></PMML>"

    cargos = parsed.tables["cargos"]
    assert "properties/P001/notes" in set(cargos["cargo_path"])
    assert "unrelated/readme.txt" not in set(cargos["cargo_path"])
    extracted_paths = set().union(
        *[
            set(parsed.tables[name].get("cargo_path", pd.Series(dtype=str)))
            for name in [
                "compound_structures",
                "property_values",
                "descriptor_values",
                "prediction_values",
                "ucum_units",
                "references",
                "bibtex_entries",
                "model_pmml_files",
            ]
        ]
    )
    assert "properties/P001/notes" not in extracted_paths

    errors = parsed.tables["cargo_parse_errors"]
    assert errors["cargo_path"].tolist() == ["properties/P_BAD/values"]
    assert "CargoParseError" in errors.loc[0, "error"]

    for table in parsed.tables.values():
        forbidden_columns = {"ssbd", "hazard", "endpoint_weight", "regulatory_conclusion"}
        assert forbidden_columns.isdisjoint(set(table.columns))
