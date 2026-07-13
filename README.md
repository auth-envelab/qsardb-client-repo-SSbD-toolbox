# QsarDB Client for SSbD Toolbox Integration
`qsardb-client` is a Python package for working with QsarDB predictor models, QDB archive files, and structured QSAR/QSPR prediction outputs.
The package provides a QsarDB-native integration layer that can be used as an evidence-producing component in broader workflows, including SSbD-related toolboxes. It does not itself perform SSbD scoring, hazard classification, endpoint weighting, regulatory interpretation, or safe/unsafe decisions.

## Implementation scope
This package is a QsarDB-native Python integration layer.
This is not an SSbD scoring layer. It does not produce hazard conclusions, endpoint weighting, regulatory conclusions, or safe/unsafe decisions.
Accepted capabilities include:
- typed schemas
- predictor catalogue parsing
- remote predictor client
- optional chemistry normalization
- neutral export utilities
- CLI for catalogue refresh and remote prediction
- optional HTTP API server exposing catalogue refresh and remote prediction
- direct archive download from a caller-supplied URL
- local QDB ZIP structural parser skeleton
- QDB archive cargo extraction
- run-reporting and reproducibility summaries
- model capability matrix
- OAI-PMH public metadata discovery
- optional local toolkit wrapper skeleton

## Features
- Discover structure-callable QsarDB predictor models.
- Run SMILES/InChI structures against QsarDB predictor models.
- Export prediction results as CSV, JSON, or Parquet.
- Summarize prediction runs.
- Parse local QDB archive ZIP files.
- Extract neutral archive cargo tables.
- Harvest public OAI-PMH repository metadata.
- Prepare model capability matrices.
- Provide an optional local toolkit wrapper skeleton for externally supplied QsarDB toolkit files.

## Installation
From the repository root:
```powershell
python -m pip install -e ".[dev]"
```
Run tests:
```powershell
python -m pytest
```
Check the CLI:
```powershell
qsardb-client --help
python -m qsardb_client.cli --help
```

## Input format
Prediction input is a CSV file with these columns:
```csv
compound_id,input_structure
cmpd_0001,CCO
cmpd_0002,CC(=O)O
cmpd_0003,c1ccccc1
```

The workflow is substance-count agnostic. For `N` input substances and `M` model entries, the expected number of prediction records is:
```text
N × M
```

## Fetch predictor models
```powershell
New-Item -ItemType Directory -Force -Path ".\runs\pilot" | Out-Null

qsardb-client catalog refresh `
  --out ".\runs\pilot\models.json" `
  --format json
```

## Run predictions
```powershell
qsardb-client predict `
  --input ".\compounds_pilot.csv" `
  --models ".\runs\pilot\models.json" `
  --out ".\runs\pilot\predictions.csv" `
  --format csv `
  --cache-dir ".\runs\pilot\cache" `
  --concurrency 1 `
  --request-delay-seconds 0.5 `
  --retry-delay-seconds 1.0 `
  --retries 2
```

## Structured outputs
Prediction outputs are written as long-form records containing compound identity, model provenance, raw QsarDB response text, parsed result fields, status, and errors.
Important columns include:
```text
compound_id
input_structure
handle
model_id
endpoint
model_type
prediction_mode
status
result_name
result_value
result_float
raw_response
error
predicted_at
```
`raw_response` and `result_value` should be treated as the authoritative prediction text. `result_float` is a convenience extraction and may not fully represent formula-style responses.

## Generate run summaries
```python
import pandas as pd
from qsardb_client.run import write_run_summary_files

predictions = pd.read_csv("runs/pilot/predictions.csv")
models = pd.read_json("runs/pilot/models.json")
compounds = pd.read_csv("compounds_pilot.csv")

write_run_summary_files(
    predictions=predictions,
    output_dir="runs/pilot/summary",
    models=models,
    input_compounds=compounds,
    input_file="compounds_pilot.csv",
    models_file="runs/pilot/models.json",
    predictions_file="runs/pilot/predictions.csv",
)
```

This creates:
```text
endpoint_status_summary.csv
compound_status_summary.csv
model_status_summary.csv
model_error_summary.csv
run_metadata.json
```

## Local QDB archive parsing
```python
from qsardb_client.archive import QDBArchiveParser
parsed = QDBArchiveParser().parse("path/to/archive.qdb.zip")
for name, table in parsed.tables.items():
    print(name, table.shape)
```
The archive parser extracts neutral structural and cargo tables. It does not evaluate models or calculate descriptors.

## Public repository metadata
```python
from qsardb_client.repository import OAIPMHClient, records_to_manifest
with OAIPMHClient() as client:
    records = client.list_records(metadata_prefix="oai_dc", max_pages=1)
manifest = records_to_manifest(records)
print(manifest.head())
```
This is metadata discovery only. It does not download archives.

## Optional local toolkit wrapper
The package includes a wrapper skeleton for externally supplied QsarDB toolkit JAR files. Java and toolkit files are not required for installation or tests.
```python
from qsardb_client.local import QsarDBToolkitBackend, QsarDBToolkitConfig

backend = QsarDBToolkitBackend(QsarDBToolkitConfig())
availability = backend.check_availability()
print(availability)
```

## Development
Install development dependencies:
```powershell
python -m pip install -e ".[dev]"
```
Run tests:
```powershell
python -m pytest
```

## HTTP API server
An optional FastAPI server exposes the same catalogue refresh and prediction capabilities as the CLI over HTTP, for integration into a broader platform. It carries the same implementation scope as the rest of the package: no SSbD scoring, hazard classification, or regulatory interpretation.

Install the server dependencies and run it:
```powershell
python -m pip install -e ".[api]"
qsardb-client-server
```
By default it listens on `0.0.0.0:8000` (override with the `QSARDB_SERVER_HOST` / `QSARDB_SERVER_PORT` environment variables).

Endpoints:
```text
GET  /health                    Liveness check
POST /catalog/refresh           Fetch (or parse an uploaded HTML file for) the predictor catalogue
POST /predict                   Run remote predictions for uploaded compounds against a single model (N compounds x 1 model)
POST /predict/batch             Run remote predictions for uploaded compounds against a models JSON array (N compounds x M models)
```
Interactive OpenAPI docs are available at `/docs` while the server is running.

Example: refresh the catalogue from the live QsarDB site:
```bash
curl -X POST "http://localhost:8000/catalog/refresh" -F "format=json" -o models.json
```

Example: run predictions against a single model (`handle`, `model_id`, `endpoint`, and `model_type` are one entry from the `/catalog/refresh` response):
```bash
curl -X POST "http://localhost:8000/predict" \
  -F "format=csv" \
  -F "handle=10967/257" \
  -F "model_id=M1" \
  -F "endpoint=Intrinsic aqueous solubility" \
  -F "model_type=regression" \
  -F "input=@compounds_pilot.csv;type=text/csv" \
  -o predictions.csv
```

Example: run predictions against many models at once, mirroring the CLI's `predict` command:
```bash
curl -X POST "http://localhost:8000/predict/batch" \
  -F "format=csv" \
  -F "concurrency=1" \
  -F "request_delay_seconds=0.5" \
  -F "retry_delay_seconds=1.0" \
  -F "retries=2" \
  -F "input=@compounds_pilot.csv;type=text/csv" \
  -F "models=@runs/pilot/models.json;type=application/json" \
  -o predictions.csv
```
Both prediction endpoints accept `format` as `json`, `csv`, or `parquet`, and return the output directly in the response body rather than writing to a shared filesystem. The server does not accept a `cache-dir` path from callers, since it runs as a shared, potentially multi-tenant process — request-level response caching from the CLI is not exposed over HTTP.

## Docker
Build the image from the repository root:
```powershell
docker build -t qsardb-client:local .
```
By default, the container runs the HTTP API server:
```powershell
docker run --rm -p 8000:8000 qsardb-client:local
```
To run the CLI in a container instead, override the default command:
```powershell
docker run --rm qsardb-client:local --help
docker run --rm qsardb-client:local catalog --help
```

## License
MIT
