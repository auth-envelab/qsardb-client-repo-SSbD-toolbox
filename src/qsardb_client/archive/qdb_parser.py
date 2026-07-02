"""Shallow structural parser for local QDB ZIP archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile

import pandas as pd

from qsardb_client.archive.cargos import (
    CargoParseError,
    make_cargo_error_record,
    parse_references_tsv,
    parse_two_column_tsv,
    read_text_cargo,
)


class QDBParseError(Exception):
    """Base exception for QDB parsing failures."""


@dataclass(frozen=True)
class ParsedQDBArchive:
    path: Path
    entries: list[str]
    archive_metadata: dict[str, Any]
    containers: dict[str, list[dict[str, Any]]]
    tables: dict[str, pd.DataFrame]


class QDBArchiveParser:
    CONTAINER_NAMES = (
        "compounds",
        "properties",
        "descriptors",
        "models",
        "predictions",
    )

    def parse(self, path: str | Path) -> ParsedQDBArchive:
        archive_path = Path(path)
        if not archive_path.exists():
            raise QDBParseError(f"QDB archive does not exist: {archive_path}")
        if not archive_path.is_file():
            raise QDBParseError(f"QDB archive path is not a file: {archive_path}")
        if not is_zipfile(archive_path):
            raise QDBParseError(f"QDB archive is not a ZIP file: {archive_path}")

        try:
            with ZipFile(archive_path) as zip_file:
                infos = zip_file.infolist()
                entry_names = [info.filename for info in infos]
                entries_table = self._entries_table(infos)
                present_containers = self._present_containers(entry_names)
                archive_metadata = self._archive_metadata(zip_file, entry_names)
                xml_rows = self._xml_rows(zip_file, infos, present_containers)
                cargo_rows = self._cargo_rows(infos, present_containers)
                extracted_cargos = self._extract_cargos(zip_file, cargo_rows)
        except BadZipFile as exc:
            raise QDBParseError(f"QDB archive is not a readable ZIP file: {archive_path}") from exc
        except OSError as exc:
            raise QDBParseError(f"Could not read QDB archive: {exc}") from exc

        containers = {name: [] for name in present_containers}
        for row in xml_rows:
            containers[row["container"]].append(dict(row))

        tables = {
            "entries": entries_table,
            "archive_metadata": self._dataframe(
                [archive_metadata] if archive_metadata else [],
                ["xml_path", "root_tag", "attributes", "text"],
            ),
            "containers": self._containers_table(present_containers, entry_names),
            "xml_files": self._dataframe(
                xml_rows,
                [
                    "container",
                    "item_id",
                    "xml_path",
                    "root_tag",
                    "attributes",
                    "text",
                    "parse_error",
                ],
            ),
            "cargos": self._dataframe(
                cargo_rows,
                ["container", "item_id", "cargo_path", "cargo_name", "size"],
            ),
            "compound_structures": self._dataframe_with_columns(
                extracted_cargos["compound_structures"],
                [
                    "container",
                    "item_id",
                    "cargo_path",
                    "cargo_name",
                    "structure_format",
                    "structure_text",
                ],
            ),
            "property_values": self._dataframe_with_columns(
                extracted_cargos["property_values"],
                ["container", "item_id", "cargo_path", "compound_id", "value"],
            ),
            "descriptor_values": self._dataframe_with_columns(
                extracted_cargos["descriptor_values"],
                ["container", "item_id", "cargo_path", "compound_id", "value"],
            ),
            "prediction_values": self._dataframe_with_columns(
                extracted_cargos["prediction_values"],
                ["container", "item_id", "cargo_path", "compound_id", "value"],
            ),
            "ucum_units": self._dataframe_with_columns(
                extracted_cargos["ucum_units"],
                ["container", "item_id", "cargo_path", "cargo_name", "unit_text"],
            ),
            "references": self._dataframe_with_columns(
                extracted_cargos["references"],
                ["container", "item_id", "cargo_path", "compound_id", "reference_id"],
            ),
            "bibtex_entries": self._dataframe_with_columns(
                extracted_cargos["bibtex_entries"],
                ["container", "item_id", "cargo_path", "cargo_name", "bibtex_text"],
            ),
            "model_pmml_files": self._dataframe_with_columns(
                extracted_cargos["model_pmml_files"],
                ["container", "item_id", "cargo_path", "cargo_name", "pmml_text"],
            ),
            "cargo_parse_errors": self._dataframe_with_columns(
                extracted_cargos["cargo_parse_errors"],
                ["container", "item_id", "cargo_path", "cargo_name", "error"],
            ),
        }

        return ParsedQDBArchive(
            path=archive_path,
            entries=entry_names,
            archive_metadata=archive_metadata,
            containers=containers,
            tables=tables,
        )

    def _entries_table(self, infos: list[Any]) -> pd.DataFrame:
        rows = [
            {
                "path": info.filename,
                "is_dir": info.is_dir(),
                "size": info.file_size,
            }
            for info in infos
        ]
        return self._dataframe(rows, ["path", "is_dir", "size"])

    def _present_containers(self, entry_names: list[str]) -> list[str]:
        present = set()
        for entry_name in entry_names:
            parts = self._parts(entry_name)
            if parts and parts[0] in self.CONTAINER_NAMES:
                present.add(parts[0])
        return [name for name in self.CONTAINER_NAMES if name in present]

    def _archive_metadata(
        self,
        zip_file: ZipFile,
        entry_names: list[str],
    ) -> dict[str, Any]:
        if "archive.xml" not in entry_names:
            return {}
        return self._parse_xml_file(zip_file, "archive.xml")

    def _xml_rows(
        self,
        zip_file: ZipFile,
        infos: list[Any],
        present_containers: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        present = set(present_containers)
        for info in infos:
            if info.is_dir():
                continue

            parts = self._parts(info.filename)
            if len(parts) < 3 or parts[0] not in present:
                continue
            if not parts[-1].lower().endswith(".xml"):
                continue

            parsed = self._parse_xml_file(zip_file, info.filename)
            rows.append(
                {
                    "container": parts[0],
                    "item_id": parts[1],
                    "xml_path": info.filename,
                    "root_tag": parsed.get("root_tag"),
                    "attributes": parsed.get("attributes", {}),
                    "text": parsed.get("text"),
                    "parse_error": parsed.get("parse_error"),
                }
            )
        return rows

    def _extract_cargos(
        self,
        zip_file: ZipFile,
        cargo_rows: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        extracted: dict[str, list[dict[str, Any]]] = {
            "compound_structures": [],
            "property_values": [],
            "descriptor_values": [],
            "prediction_values": [],
            "ucum_units": [],
            "references": [],
            "bibtex_entries": [],
            "model_pmml_files": [],
            "cargo_parse_errors": [],
        }
        for row in cargo_rows:
            container = row["container"]
            item_id = row["item_id"]
            cargo_path = row["cargo_path"]
            cargo_name = row["cargo_name"]
            normalized_name = cargo_name.lower()

            target = self._cargo_target(container, normalized_name)
            if target is None:
                continue

            try:
                data = zip_file.read(cargo_path)
                self._extract_cargo(
                    extracted,
                    target,
                    data,
                    container=container,
                    item_id=item_id,
                    cargo_path=cargo_path,
                    cargo_name=cargo_name,
                    normalized_name=normalized_name,
                )
            except Exception as exc:
                extracted["cargo_parse_errors"].append(
                    make_cargo_error_record(
                        container=container,
                        item_id=item_id,
                        cargo_path=cargo_path,
                        cargo_name=cargo_name,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return extracted

    def _cargo_target(self, container: str, cargo_name: str) -> str | None:
        if container == "compounds" and cargo_name in {"daylight-smiles", "mdl-molfile"}:
            return "compound_structures"
        if container == "compounds" and cargo_name == "bibtex":
            return "bibtex_entries"
        if container in {"properties", "descriptors", "predictions"}:
            if cargo_name == "bibtex":
                return "bibtex_entries"
            if cargo_name in {"values", "ucum", "references"}:
                return cargo_name
        if container == "models" and cargo_name in {"pmml", "bibtex"}:
            return "model_pmml_files" if cargo_name == "pmml" else "bibtex_entries"
        return None

    def _extract_cargo(
        self,
        extracted: dict[str, list[dict[str, Any]]],
        target: str,
        data: bytes,
        *,
        container: str,
        item_id: str,
        cargo_path: str,
        cargo_name: str,
        normalized_name: str,
    ) -> None:
        if target == "compound_structures":
            structure_format = "smiles" if normalized_name == "daylight-smiles" else "mdl-molfile"
            extracted["compound_structures"].append(
                {
                    "container": container,
                    "item_id": item_id,
                    "cargo_path": cargo_path,
                    "cargo_name": cargo_name,
                    "structure_format": structure_format,
                    "structure_text": read_text_cargo(data),
                }
            )
            return

        if target == "values":
            table_name = {
                "properties": "property_values",
                "descriptors": "descriptor_values",
                "predictions": "prediction_values",
            }[container]
            parsed = parse_two_column_tsv(
                read_text_cargo(data),
                value_column_name="value",
                source_path=cargo_path,
            )
            extracted[table_name].extend(
                self._prefixed_cargo_records(
                    parsed,
                    container=container,
                    item_id=item_id,
                    cargo_path=cargo_path,
                )
            )
            return

        if target == "ucum":
            extracted["ucum_units"].append(
                {
                    "container": container,
                    "item_id": item_id,
                    "cargo_path": cargo_path,
                    "cargo_name": cargo_name,
                    "unit_text": read_text_cargo(data),
                }
            )
            return

        if target == "references":
            parsed = parse_references_tsv(read_text_cargo(data), source_path=cargo_path)
            extracted["references"].extend(
                self._prefixed_cargo_records(
                    parsed,
                    container=container,
                    item_id=item_id,
                    cargo_path=cargo_path,
                )
            )
            return

        if target == "bibtex_entries":
            extracted["bibtex_entries"].append(
                {
                    "container": container,
                    "item_id": item_id,
                    "cargo_path": cargo_path,
                    "cargo_name": cargo_name,
                    "bibtex_text": read_text_cargo(data),
                }
            )
            return

        if target == "model_pmml_files":
            extracted["model_pmml_files"].append(
                {
                    "container": container,
                    "item_id": item_id,
                    "cargo_path": cargo_path,
                    "cargo_name": cargo_name,
                    "pmml_text": read_text_cargo(data),
                }
            )
            return

        raise CargoParseError(f"Unsupported cargo extraction target: {target}")

    def _prefixed_cargo_records(
        self,
        parsed: pd.DataFrame,
        *,
        container: str,
        item_id: str,
        cargo_path: str,
    ) -> list[dict[str, Any]]:
        records = []
        for record in parsed.to_dict("records"):
            record.pop("source_path", None)
            records.append(
                {
                    "container": container,
                    "item_id": item_id,
                    "cargo_path": cargo_path,
                    **record,
                }
            )
        return records

    def _cargo_rows(
        self,
        infos: list[Any],
        present_containers: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        present = set(present_containers)
        for info in infos:
            if info.is_dir():
                continue

            parts = self._parts(info.filename)
            if len(parts) < 3 or parts[0] not in present:
                continue
            if parts[-1].lower().endswith(".xml"):
                continue

            rows.append(
                {
                    "container": parts[0],
                    "item_id": parts[1],
                    "cargo_path": info.filename,
                    "cargo_name": parts[-1],
                    "size": info.file_size,
                }
            )
        return rows

    def _containers_table(
        self,
        present_containers: list[str],
        entry_names: list[str],
    ) -> pd.DataFrame:
        rows = []
        for container in present_containers:
            item_ids = {
                parts[1]
                for entry_name in entry_names
                if (parts := self._parts(entry_name))
                and len(parts) >= 2
                and parts[0] == container
                and parts[1]
            }
            rows.append(
                {
                    "container": container,
                    "present": True,
                    "item_count": len(item_ids),
                }
            )
        return self._dataframe(rows, ["container", "present", "item_count"])

    def _parse_xml_file(self, zip_file: ZipFile, xml_path: str) -> dict[str, Any]:
        try:
            with zip_file.open(xml_path) as file_obj:
                root = ElementTree.parse(file_obj).getroot()
        except ElementTree.ParseError as exc:
            return {
                "xml_path": xml_path,
                "root_tag": None,
                "attributes": {},
                "text": None,
                "parse_error": str(exc),
            }

        return {
            "xml_path": xml_path,
            "root_tag": self._local_tag(root.tag),
            "attributes": dict(root.attrib),
            "text": self._text_or_none(root.text),
        }

    def _local_tag(self, tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag

    def _text_or_none(self, text: str | None) -> str | None:
        if text is None:
            return None
        stripped = text.strip()
        return stripped or None

    def _parts(self, path: str) -> list[str]:
        return [part for part in path.split("/") if part]

    def _dataframe(self, rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=columns)

    def _dataframe_with_columns(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=columns)
        dataframe = pd.DataFrame(rows)
        for column in columns:
            if column not in dataframe.columns:
                dataframe[column] = None
        extra_columns = [column for column in dataframe.columns if column not in columns]
        return dataframe[columns + extra_columns]
