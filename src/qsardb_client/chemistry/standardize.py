"""Optional SMILES canonicalization utilities."""

from __future__ import annotations

import importlib
from typing import Any

from qsardb_client.schemas import ChemicalRecord


class ChemistryNormalizationError(Exception):
    """Base exception for chemistry normalization errors."""


class RDKitUnavailableError(ChemistryNormalizationError):
    """Raised when RDKit-dependent behavior is requested but RDKit is unavailable."""


class InvalidStructureError(ChemistryNormalizationError):
    """Raised when a structure cannot be parsed or normalized."""


def _load_rdkit_chem() -> Any | None:
    try:
        return importlib.import_module("rdkit.Chem")
    except ImportError:
        return None


def is_rdkit_available() -> bool:
    return _load_rdkit_chem() is not None


def canonicalize_smiles(
    smiles: str,
    *,
    require_rdkit: bool = False,
) -> str | None:
    stripped = smiles.strip()
    if not stripped and require_rdkit:
        raise InvalidStructureError("SMILES is empty.")

    chem = _load_rdkit_chem()
    if chem is None:
        if require_rdkit:
            raise RDKitUnavailableError("RDKit is required but is not available.")
        return None

    if not stripped:
        raise InvalidStructureError("SMILES is empty.")

    mol = chem.MolFromSmiles(stripped)
    if mol is None:
        raise InvalidStructureError("SMILES could not be parsed.")

    return chem.MolToSmiles(mol, canonical=True)


def normalize_chemical_record(
    compound_id: str,
    input_structure: str,
    *,
    require_rdkit: bool = False,
) -> ChemicalRecord:
    canonical_smiles = canonicalize_smiles(
        input_structure,
        require_rdkit=require_rdkit,
    )
    return ChemicalRecord(
        compound_id=compound_id,
        input_structure=input_structure,
        canonical_smiles=canonical_smiles,
    )


def normalize_chemical_records(
    records: list[dict[str, str]] | list[ChemicalRecord],
    *,
    require_rdkit: bool = False,
) -> list[ChemicalRecord]:
    normalized_records: list[ChemicalRecord] = []
    for record in records:
        if isinstance(record, ChemicalRecord):
            if record.canonical_smiles:
                normalized_records.append(record)
                continue

            normalized_records.append(
                ChemicalRecord(
                    compound_id=record.compound_id,
                    input_structure=record.input_structure,
                    canonical_smiles=canonicalize_smiles(
                        record.input_structure,
                        require_rdkit=require_rdkit,
                    ),
                    handle=record.handle,
                    metadata=record.metadata,
                )
            )
            continue

        missing_keys = [
            key
            for key in ("compound_id", "input_structure")
            if key not in record
        ]
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise ValueError(f"Chemical record is missing required key(s): {missing}")

        normalized_records.append(
            normalize_chemical_record(
                record["compound_id"],
                record["input_structure"],
                require_rdkit=require_rdkit,
            )
        )

    return normalized_records
