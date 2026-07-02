from __future__ import annotations


def test_public_imports_still_work() -> None:
    from qsardb_client import ChemicalRecord, QsarDBClient

    assert QsarDBClient(base_url="https://example.invalid")
    assert ChemicalRecord(compound_id="compound-1", input_structure="CCO")


def test_predictor_imports_still_work() -> None:
    from qsardb_client.predictor import PredictorCatalog, RemotePredictorClient

    assert PredictorCatalog
    assert RemotePredictorClient


def test_chemistry_imports_still_work() -> None:
    from qsardb_client.chemistry import canonicalize_smiles, normalize_chemical_record

    assert canonicalize_smiles
    assert normalize_chemical_record


def test_export_imports_still_work() -> None:
    from qsardb_client.export import evidence_bundle_to_tables, records_to_json

    assert evidence_bundle_to_tables
    assert records_to_json


def test_archive_imports_still_work() -> None:
    from qsardb_client.archive import ArchiveDownloader, QDBArchiveParser

    assert ArchiveDownloader
    assert QDBArchiveParser


def test_cli_main_is_importable() -> None:
    from qsardb_client.cli import main

    assert main


def test_no_archive_repository_or_ssbd_cli_commands_are_available(capsys) -> None:
    from qsardb_client.cli import main

    for command in ("archive", "repository", "ssbd"):
        assert main([command, "--help"]) != 0

    assert "invalid choice" in capsys.readouterr().err
