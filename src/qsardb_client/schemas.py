"""Typed schemas for QsarDB-native records."""

from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import JsonValue


JsonObject = dict[str, JsonValue]


class QsarDBBaseModel(BaseModel):
    """Shared model configuration for strict, serializable records."""

    model_config = ConfigDict(extra="forbid")


class ChemicalRecord(QsarDBBaseModel):
    compound_id: str
    input_structure: str
    canonical_smiles: str | None = None
    handle: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class QsarDBArchiveRecord(QsarDBBaseModel):
    handle: str
    archive_id: str | None = None
    title: str | None = None
    source_url: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class QsarDBModelRecord(QsarDBBaseModel):
    handle: str
    model_id: str
    archive_id: str | None = None
    name: str | None = None
    endpoint: str
    model_type: str
    version: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class QsarDBModelCapability(QsarDBBaseModel):
    handle: str
    model_id: str
    endpoint: str
    model_type: str
    prediction_modes: list[str] = Field(default_factory=list)
    result_names: list[str] = Field(default_factory=list)
    result_units: list[str] = Field(default_factory=list)
    applicability_domain_available: bool = False
    metadata: JsonObject = Field(default_factory=dict)


class QsarDBPredictionRecord(QsarDBBaseModel):
    compound_id: str
    input_structure: str
    canonical_smiles: str | None = None
    handle: str
    model_id: str
    endpoint: str
    model_type: str
    prediction_mode: str
    status: str
    result_name: str | None = None
    result_value: JsonValue = None
    result_float: float | None = None
    result_unit: str | None = None
    raw_response: str | None = None
    applicability_domain: JsonObject | None = None
    similar_compounds: list[JsonObject] = Field(default_factory=list)
    error: str | None = None
    predicted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QsarDBEvidenceBundle(QsarDBBaseModel):
    chemicals: list[ChemicalRecord] = Field(default_factory=list)
    archives: list[QsarDBArchiveRecord] = Field(default_factory=list)
    models: list[QsarDBModelRecord] = Field(default_factory=list)
    capabilities: list[QsarDBModelCapability] = Field(default_factory=list)
    predictions: list[QsarDBPredictionRecord] = Field(default_factory=list)
    extracted_tables: list[JsonObject] = Field(default_factory=list)
    raw_files: list[JsonObject] = Field(default_factory=list)
