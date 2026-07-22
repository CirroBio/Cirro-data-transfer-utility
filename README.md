# Cirro Data Transfer Utility

Interactive tool to bulk-transfer files from external sources into
[Cirro](https://cirro.bio) as complete, immutable datasets — driven by two
CSVs, resumable across restarts, with live progress and end-to-end checksum
verification.

- **Sources:** `https://`, `s3://`, `gs://`, `ftp://`, `sftp://`, and a
  `syn://` (Synapse) interface stub.
- **Resumable:** transfer state, the queue, and the Cirro manifest cache all
  live in SQLite, so a restart resumes cleanly and an interrupted upload
  continues where it left off.
- **Verified at every hop:** source→local (download), local→Cirro (S3
  server-side CRC64NVME), and an end-to-end re-check before a dataset is
  finalized.

## Architecture

- **Backend** — FastAPI (`backend/`), a background transfer worker, and SQLite.
- **Frontend** — React + Vite + TypeScript (`frontend/`), served by the backend
  in production.

```
CSVs ─▶ csv_loader ─▶ SQLite (datasets/files/queue/manifest_cache)
                          │
   cirro_gateway ─▶ reconcile ─▶ status badges (PRESENT/MISMATCH/PENDING)
                          │
                     queue worker ─▶ transfer.py ─▶ sources/* (download→tempdir)
                          │                    └─▶ cirro_gateway (create/upload/verify)
   FastAPI + SSE ◀────────┘  ◀── live progress ──┘
```

## Setup

### Backend

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
npm run build      # produces frontend/dist, served by the backend
```

## Run

```bash
source .venv/bin/activate
uvicorn backend.app:app --port 8000
# open http://localhost:8000
```

For frontend development with hot reload, run `npm run dev` in `frontend/`
(it proxies API calls to the backend on :8000).

### Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CIRRO_BASE_URL` | `app.cirro.bio` | Cirro tenant host |
| `CIRRO_TRANSFER_HOME` | `~/.cirro-transfer` | SQLite DB + staging tempdirs |
| `CIRRO_TRANSFER_CONCURRENCY` | `1` | Datasets transferred in parallel |

## Usage

1. **Log in** — click *Log in*; a device-code link + code appears. Complete it
   in your browser. The token is cached (`enable_cache=True`) so it survives
   restarts.
2. **Pick a default project** (optional) — used for datasets whose CSV row
   leaves `project` blank.
3. **Load the two CSVs** (see below) — validated and stored.
4. **Reconcile** — marks each dataset `PRESENT` (already in Cirro & matching),
   `MISMATCH`, or `PENDING`.
5. **Transfer** — enqueue pending datasets; watch live download/upload progress
   and per-file verification in the queue panel.

### CSV formats

Headers are case/spacing/underscore tolerant. See `examples/`.

**datasets.csv**

| column | required | notes |
| --- | --- | --- |
| `name` | yes | dataset name (also the reconcile key) |
| `data type` | yes | a Cirro **ingest process** name or id |
| `description` | no | |
| `project` | no | name or id; blank → UI default project |
| `folder path` | no | added as a `folder://<path>` tag |
| `tags` | no | `;`-separated extra tags |

**files.csv**

| column | required | notes |
| --- | --- | --- |
| `dataset` | yes | must match a `datasets.csv` `name` |
| `source uri` | yes | `https/s3/gs/ftp/sftp/syn` URI |
| `relative path` | yes | destination path within the dataset |
| `size` | no | expected bytes (verified after download) |
| `checksum` | no | expected checksum of the file contents |
| `checksum type` | no | `md5` / `sha256` / `crc32c` / `crc64nvme` |

### Checksum verification ladder

Per downloaded file the strongest available check is used and recorded
(shown in the UI under *Verified by*):

1. **csv** — the checksum you supplied in `files.csv`.
2. **source** — a checksum advertised by the source (S3 ETag/checksum, GCS
   md5/crc32c, HTTP Content-MD5).
3. **size** — byte size only.
4. **path** — nothing verifiable; existence only (logged as a downgrade).

On upload, Cirro/S3 verify a CRC64NVME server-side; before a dataset is
finalized, every stored file is re-validated against the local copy
(`DataPortalFile.validate`), which also guards the size-only resume path.

## How resume works

The worker does **not** use `project.upload_dataset()` (it always creates a new
dataset and cannot resume). Instead it mirrors the SDK's CLI: validate names →
`datasets.create()` (persisting the dataset id to SQLite **before** uploading) →
`datasets.upload_files()`. If interrupted, the dataset id is retained; a retry
resumes with `upload_files(resume=True)`, which skips files already uploaded
(by size), then re-verifies checksums.

## Tests

```bash
source .venv/bin/activate
pip install pytest
pytest -q
```

Covers checksum math, CSV parsing/validation, reconcile classification (with a
fake gateway), and the download verification ladder / scheme dispatch. Tests
run offline (no Cirro connection required).

## Synapse

`syn://` is registered but stubbed — `SynapseDownloader.stat/_stream` raise a
clear `NotImplementedError`. Implement them with `synapseclient` to enable it.
