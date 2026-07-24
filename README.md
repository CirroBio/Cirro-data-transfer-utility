# Cirro Data Transfer Utility

Interactive tool to bulk-transfer files from external sources into
[Cirro](https://cirro.bio) as complete, immutable datasets — driven by a
**migration plan** of two CSV tables (`dataset_plan.csv` + `file_plan.csv`),
resumable across restarts, with live progress and end-to-end checksum
verification.

The plan describes a three-level hierarchy — files organized into datasets,
datasets organized into folders within a study/project. See
[the schema](#input-schema-levels-13) below.

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
plan CSVs ─▶ csv_loader ─▶ SQLite (datasets/files/excluded/queue/manifest_cache)
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
uvicorn backend.app:app --port 8000 --env-file .env
# open http://localhost:8000
```

`--env-file .env` is optional; drop it if you export the config another way.
For frontend development with hot reload, run `npm run dev` in `frontend/`
(it proxies API calls to the backend on :8000).

### Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CIRRO_BASE_URL` | `app.cirro.bio` | Cirro tenant host |
| `CIRRO_TRANSFER_HOME` | `~/.cirro-transfer` | SQLite DB + staging tempdirs |
| `CIRRO_TRANSFER_CONCURRENCY` | `1` | Datasets transferred in parallel |

Copy `.env.example` to `.env` for the non-secret config above. It is **not**
where credentials go — see below.

## Credentials

There are two kinds of credentials, and neither is typed into the app: the app
has no field for source secrets, and Cirro uses an interactive login.

**Cirro (upload) — nothing to configure.** Click *Log in* in the app and
complete the device code in your browser once. The token is cached (under
`~/.cirro/`) and survives restarts. Do not put Cirro credentials in the
environment.

**Sources (download) — use the SDK's ambient credentials.** Each scheme
resolves its own credentials; the app never sees them:

| Scheme | Auth | Where the credential lives |
| --- | --- | --- |
| `gs://` | Application Default Credentials, else anonymous | ambient (ADC) |
| `s3://` | standard AWS chain, else unsigned | ambient (env / `~/.aws`) |
| `https://` | none (plain GET) | the URL itself — public or presigned |
| `ftp://`, `sftp://` | `user:pass` from the URI | embedded in `source_location` |

The transfer worker is a single background process, so **whatever environment
you launch `uvicorn` from is what every transfer uses**. Set source credentials
in that shell, then start the server from it.

GCS (this project's data lives in `gs://`), easiest first — a user login that
self-refreshes with no key file:

```bash
gcloud auth application-default login
```

To act as a short-lived service account instead:

```bash
gcloud auth application-default login --impersonate-service-account=SA_EMAIL@PROJECT.iam.gserviceaccount.com
```

If you were handed a key file to use temporarily, point ADC at it and delete it
when done:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/temp-key.json
```

S3 temporary (STS) credentials are read straight from the environment:

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...
```

Prefer the native credential stores (`gcloud` ADC, `~/.aws`) over raw keys in
`.env`; short-lived STS values in `.env` are an acceptable dev exception since
they expire on their own. Note that `ftp://`/`sftp://` carry the password in
`source_location` — treat any plan CSV using them as a secret.

## Usage

1. **Log in** — click *Log in*; a device-code link + code appears. Complete it
   in your browser. The token is cached (`enable_cache=True`) so it survives
   restarts.
2. **Pick a fallback project** (optional) — used only if a dataset row has no
   `study`; normally the study *is* the project.
3. **Load the plan** (`dataset_plan.csv` + `file_plan.csv`, see below) —
   validated and stored.
4. **Reconcile** — marks each dataset `PRESENT` (already in Cirro & matching),
   `MISMATCH`, or `PENDING`.
5. **Transfer** — enqueue pending datasets; watch live download/upload progress
   and per-file verification in the queue panel.

### Input schema (levels 1–3)

The plan is two CSV tables. Headers are case/spacing/underscore tolerant, but
the column names are the plan's own. See `examples/`.

A dataset's identity is the pair **(`target_dataset_name`, `cirro_folder_path`)**
— the same name recurs across folders within one study, so the name alone is
not unique. `file_plan` rows join to their dataset on that same pair.

**Level 3 — Folders.** `cirro_folder_path` is a tree **rooted at the study**.
The study is the Cirro **project**; the remainder of the path is the dataset's
folder *within* that project (recorded as a `folder://` tag). A dataset whose
`cirro_folder_path` equals its study sits at the project root.

**Level 2 — `dataset_plan.csv`** (one row per target Cirro dataset):

| column | required | notes |
| --- | --- | --- |
| `target_dataset_name` | yes* | the Cirro dataset name |
| `study` | yes* | the Cirro **project** (name or id) |
| `cirro_folder_path` | yes* | folder path, rooted at the study |
| `status` | yes | `included` (transferred) or `excluded` (recorded only) |
| `cirro_type_id` | yes* | a Cirro **ingest process** id — the dataset's type |
| `cirro_type_name` | no | display label for the type |
| `source_kind` | no | e.g. `gcs_files`, `local_sheet` |
| `source_dataset_id`, `source_subpath` | no | provenance |
| `n_files` | no | expected file count (cross-checked against `file_plan`) |
| `total_size_bytes` | no | expected total size |
| `excluded_at` | no | reason/timestamp for `excluded` rows |

\* Required on `included` rows. `excluded` rows have no Cirro target (blank
name/folder/type); they are identified by `study` + `source_dataset_id`, stored
separately, and never transferred.

**Level 1 — `file_plan.csv`** (one row per file that moves):

| column | required | notes |
| --- | --- | --- |
| `target_dataset_name` | yes | with `cirro_folder_path`, the dataset it joins |
| `cirro_folder_path` | yes | |
| `target_relative_path` | yes | destination path within the dataset |
| `source_location` | yes | `https/s3/gs/ftp/sftp/syn` source URI |
| `size_bytes` | yes | expected bytes (verified after download) |
| `hash` | no | base64-encoded MD5 of the content |
| `source_dataset_id`, `source_subpath`, `source_pathname` | no | provenance |

### Checksum verification ladder

Per downloaded file the strongest available check is used and recorded
(shown in the UI under *Verified by*):

1. **csv** — the `hash` supplied in `file_plan.csv` (base64 MD5).
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
