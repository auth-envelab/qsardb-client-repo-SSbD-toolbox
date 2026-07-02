from __future__ import annotations

from types import SimpleNamespace

import pytest

from qsardb_client.chemistry import (
    InvalidStructureError,
    RDKitUnavailableError,
    canonicalize_smiles,
    is_rdkit_available,
    normalize_chemical_record,
    normalize_chemical_records,
)
from qsardb_client.chemistry import standardize
from qsardb_client.schemas import ChemicalRecord


class FakeChem:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.seen_smiles: list[str] = []

    def MolFromSmiles(self, smiles: str) -> SimpleNamespace | None:
        self.seen_smiles.append(smiles)
        if self.invalid:
            return None
        return SimpleNamespace(smiles=smiles)

    def MolToSmiles(self, mol: SimpleNamespace, canonical: bool = True) -> str:
        assert canonical is True
        return f"canonical:{mol.smiles}"


def patch_rdkit_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_module(name: str) -> object:
        assert name == "rdkit.Chem"
        raise ImportError("RDKit unavailable")

    monkeypatch.setattr(standardize.importlib, "import_module", import_module)


def patch_rdkit_available(
    monkeypatch: pytest.MonkeyPatch,
    chem: FakeChem,
) -> None:
    def import_module(name: str) -> object:
        assert name == "rdkit.Chem"
        return chem

    monkeypatch.setattr(standardize.importlib, "import_module", import_module)


def test_is_rdkit_available_returns_false_when_import_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_rdkit_unavailable(monkeypatch)

    assert is_rdkit_available() is False


def test_canonicalize_smiles_returns_none_when_rdkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_rdkit_unavailable(monkeypatch)

    assert canonicalize_smiles(" CCO ", require_rdkit=False) is None


def test_canonicalize_smiles_raises_when_rdkit_required_and_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_rdkit_unavailable(monkeypatch)

    with pytest.raises(RDKitUnavailableError):
        canonicalize_smiles("CCO", require_rdkit=True)


def test_canonicalize_smiles_strips_whitespace_before_rdkit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)

    assert canonicalize_smiles("  CCO  ") == "canonical:CCO"
    assert chem.seen_smiles == ["CCO"]


def test_canonicalize_smiles_returns_canonical_smiles_when_rdkit_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)

    assert canonicalize_smiles("OCC") == "canonical:OCC"


def test_canonicalize_smiles_raises_invalid_when_rdkit_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem(invalid=True)
    patch_rdkit_available(monkeypatch, chem)

    with pytest.raises(InvalidStructureError):
        canonicalize_smiles("not-smiles")


def test_normalize_chemical_record_preserves_input_and_sets_canonical_smiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)

    record = normalize_chemical_record("compound-1", "  CCO  ")

    assert record.compound_id == "compound-1"
    assert record.input_structure == "  CCO  "
    assert record.canonical_smiles == "canonical:CCO"


def test_normalize_chemical_record_sets_none_when_rdkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_rdkit_unavailable(monkeypatch)

    record = normalize_chemical_record("compound-1", "CCO")

    assert record.canonical_smiles is None


def test_normalize_chemical_records_accepts_dictionaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)

    records = normalize_chemical_records(
        [{"compound_id": "compound-1", "input_structure": "CCO"}]
    )

    assert records == [
        ChemicalRecord(
            compound_id="compound-1",
            input_structure="CCO",
            canonical_smiles="canonical:CCO",
        )
    ]


def test_normalize_chemical_records_accepts_chemical_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)
    source = ChemicalRecord(compound_id="compound-1", input_structure="CCO")

    records = normalize_chemical_records([source])

    assert records[0].compound_id == "compound-1"
    assert records[0].input_structure == "CCO"
    assert records[0].canonical_smiles == "canonical:CCO"


def test_normalize_chemical_records_preserves_existing_canonical_smiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chem = FakeChem()
    patch_rdkit_available(monkeypatch, chem)
    source = ChemicalRecord(
        compound_id="compound-1",
        input_structure="not-reprocessed",
        canonical_smiles="already-canonical",
    )

    records = normalize_chemical_records([source])

    assert records == [source]
    assert chem.seen_smiles == []


def test_normalize_chemical_records_raises_for_missing_dictionary_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_rdkit_unavailable(monkeypatch)

    with pytest.raises(ValueError, match="compound_id"):
        normalize_chemical_records([{"input_structure": "CCO"}])
