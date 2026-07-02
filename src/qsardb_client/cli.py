"""Command-line interface for accepted QsarDB client capabilities."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from qsardb_client.chemistry.standardize import (
    ChemistryNormalizationError,
    normalize_chemical_records,
)
from qsardb_client.export import (
    ExportError,
    records_to_csv,
    records_to_json,
    records_to_parquet,
)
from qsardb_client.predictor.catalog import (
    PredictorCatalog,
    parse_predictor_catalog_html,
)
from qsardb_client.predictor.remote import RemotePredictorClient
from qsardb_client.schemas import ChemicalRecord, QsarDBModelRecord, QsarDBPredictionRecord


def _print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qsardb-client",
        description="QsarDB-native client command-line utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_parser = subparsers.add_parser(
        "catalog",
        help="Work with the QsarDB predictor catalogue.",
    )
    catalog_subparsers = catalog_parser.add_subparsers(
        dest="catalog_command",
        required=True,
    )
    refresh_parser = catalog_subparsers.add_parser(
        "refresh",
        help="Fetch or parse the predictor catalogue.",
    )
    refresh_parser.add_argument("--out", required=True, type=Path)
    refresh_parser.add_argument("--format", required=True, choices=["json", "csv"])
    refresh_parser.add_argument("--html-file", type=Path)
    refresh_parser.set_defaults(handler=_handle_catalog_refresh)

    predict_parser = subparsers.add_parser(
        "predict",
        help="Run remote QsarDB predictions for compounds and models.",
    )
    predict_parser.add_argument("--input", required=True, type=Path)
    predict_parser.add_argument("--models", required=True, type=Path)
    predict_parser.add_argument("--out", required=True, type=Path)
    predict_parser.add_argument("--format", required=True, choices=["json", "csv", "parquet"])
    predict_parser.add_argument("--cache-dir", type=Path)
    predict_parser.add_argument("--require-rdkit", action="store_true")
    predict_parser.add_argument("--concurrency", type=int, default=2)
    predict_parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    predict_parser.add_argument("--retry-delay-seconds", type=float, default=0.0)
    predict_parser.add_argument("--retries", type=int, default=2)
    predict_parser.set_defaults(handler=_handle_predict)

    return parser


def _handle_catalog_refresh(args: argparse.Namespace) -> int:
    try:
        if args.html_file is not None:
            html_path = Path(args.html_file)
            if not html_path.is_file():
                _print_error(f"HTML file not found: {html_path}")
                return 1
            records = parse_predictor_catalog_html(html_path.read_text(encoding="utf-8"))
        else:
            records = PredictorCatalog().fetch_models()

        if args.format == "json":
            records_to_json(records, args.out)
        elif args.format == "csv":
            records_to_csv(records, args.out)
        else:
            _print_error(f"Unsupported output format: {args.format}")
            return 1
    except (OSError, ExportError, ValueError) as exc:
        _print_error(str(exc))
        return 1

    return 0


def _read_compounds_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"input compounds CSV is missing: {path}")

    dataframe = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = [
        column
        for column in ("compound_id", "input_structure")
        if column not in dataframe.columns
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"compounds CSV is missing required column(s): {missing}")

    return [
        {
            "compound_id": str(row["compound_id"]),
            "input_structure": str(row["input_structure"]),
        }
        for row in dataframe[["compound_id", "input_structure"]].to_dict("records")
    ]


def _read_models_json(path: Path) -> list[QsarDBModelRecord]:
    if not path.is_file():
        raise ValueError(f"models JSON is missing: {path}")

    with path.open("r", encoding="utf-8") as file_obj:
        payload: Any = json.load(file_obj)

    if not isinstance(payload, list):
        raise ValueError("models JSON must contain a JSON array")

    return [QsarDBModelRecord.model_validate(item) for item in payload]


async def _predict_many(
    chemicals: list[ChemicalRecord],
    models: list[QsarDBModelRecord],
    args: argparse.Namespace,
) -> list[QsarDBPredictionRecord]:
    async with RemotePredictorClient(
        cache_dir=args.cache_dir,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay_seconds,
        request_delay_seconds=args.request_delay_seconds,
        concurrency=args.concurrency,
    ) as predictor:
        return await predictor.predict_many(chemicals, models)


def _write_records(records: list[QsarDBPredictionRecord], args: argparse.Namespace) -> None:
    if args.format == "json":
        records_to_json(records, args.out)
        return
    if args.format == "csv":
        records_to_csv(records, args.out)
        return
    if args.format == "parquet":
        records_to_parquet(records, args.out)
        return

    raise ValueError(f"Unsupported output format: {args.format}")


def _handle_predict(args: argparse.Namespace) -> int:
    try:
        compound_rows = _read_compounds_csv(args.input)
        chemicals = normalize_chemical_records(
            compound_rows,
            require_rdkit=args.require_rdkit,
        )
        models = _read_models_json(args.models)
        predictions = asyncio.run(_predict_many(chemicals, models, args))
        _write_records(predictions, args)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ValidationError,
        ChemistryNormalizationError,
        ExportError,
    ) as exc:
        _print_error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _print_error(f"prediction execution failed: {exc}")
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1

    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())
