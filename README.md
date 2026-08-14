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
   FastAPI events ◀───────┘  ◀── live progress ──┘
```

Live progress reaches the SPA over SSE (`/events`) where the network allows it.
If the opening frame does not arrive within a few seconds — the signature of a
proxy that buffers or drops streaming responses — the client falls back to
polling `/events/poll` once a second for the same events, keyed by a sequence
number so nothing is applied twice. Set `CIRRO_TRANSFER_EVENTS_TRANSPORT=poll`
in a deployment known to block SSE to skip the attempt.

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
set -a; . ./.env; set +a          # export the config + source credentials
uvicorn backend.app:app --port 8000
# open http://localhost:8000
```

Source `.env` rather than passing `--env-file .env`: uvicorn loads that file
with `load_dotenv()`, which does **not** override variables already exported in
your shell, so a stale `AWS_*` left over from an earlier session silently wins
over the file (the resulting failure surfaces as an opaque `403`, because the
S3 downloader retries unsigned when a signed request fails).

### Live reload

Two servers, one per side. Backend, restarting on any Python change:

```bash
set -a; . ./.env; set +a
uvicorn backend.app:app --port 8000 --reload --timeout-graceful-shutdown 1
```

`--timeout-graceful-shutdown 1` is not optional here: the SPA holds `/events`
open as an SSE stream, and without a shutdown deadline every reload stalls at
`Waiting for connections to close` until you close the browser tab. (It does no
harm under `CIRRO_TRANSFER_EVENTS_TRANSPORT=poll`, where no stream is held
open.)

Frontend, in a second shell — Vite serves the SPA with hot module replacement
and proxies API paths to the backend on :8000. Open the URL it prints (:5173
unless that port is taken), **not** :8000, which serves the last
`npm run build` output and won't reflect your edits:

```bash
cd frontend
npm run dev
```

`--reload` restarts the whole process, which kills the transfer worker thread
along with any transfer in flight. A dataset interrupted this way resumes on
retry (its uploaded files are skipped), but avoid editing backend code during a
long transfer.

### Docker

The image builds the frontend and serves it from the backend, so it needs no
setup steps beyond the build:

```bash
docker build -t cirro-data-transfer .
```

Build for the architecture the deployment runs on, not the one you build on. A
Cirro workspace is x86_64, so an image built on an Apple Silicon Mac fails at
startup with `exec format error` — the manifest is arm64 and nothing in the
workspace reports why. Name the platform explicitly when the two differ:

```bash
docker buildx build --platform linux/amd64 -t cirro-data-transfer .
```

To publish a build for a Cirro workspace to run, `scripts/publish_image.sh`
logs docker into public ECR with your AWS credentials, builds for `linux/amd64`,
and pushes to `public.ecr.aws/cirrobio/data-transfer` tagged with the current
commit. It refuses a dirty tree, since that tag would otherwise name a commit
the image does not contain:

```bash
bash scripts/publish_image.sh
```

```bash
docker run --rm -p 8000:8000 -v cirro-transfer-home:/home/cirro cirro-data-transfer
```

Everything the app writes goes to `/home/cirro`, so that one mount covers all
of it: `transfer.db`, the `staging/` downloads (**size the mount for the
largest dataset in flight** — files are downloaded whole before upload), the
`tmp/` scratch dir that stands in for `/tmp`, and the cached Cirro login in
`.cirro/`. A container has no keyring, so the SDK stores that token as a
plaintext file — treat the volume as a secret, or drop it and log in again
after each restart.

The image sets `CIRRO_TRANSFER_HOME=/home/cirro`; that one variable moves the
DB, staging, and scratch dirs together, so a different mount point needs no
other change (`CIRRO_HOME` moves the login cache alongside it).

Source credentials work as they do outside Docker, minus the ambient stores the
container cannot see (`~/.aws`, gcloud ADC) unless you mount them: enter AWS
keys in the *Source Credentials* panel, pass them with `-e`/`--env-file .env`,
or presign `gs://` sources into `https://` URLs beforehand.

The process runs as UID 1000. With a bind mount instead of a named volume
(`-v $PWD/data:/home/cirro`), make that directory writable by UID 1000 first —
a bind mount keeps the host's ownership and masks the image's own `/home/cirro`.

### Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CIRRO_BASE_URL` | `app.cirro.bio` | Cirro tenant host |
| `CIRRO_TRANSFER_HOME` | `~/.cirro-transfer` | SQLite DB + staging and scratch tempdirs |
| `CIRRO_TRANSFER_CONCURRENCY` | `1` | Datasets transferred in parallel |

Copy `.env.example` to `.env` for the config above. Cirro credentials never go
there; short-lived source credentials may — see below.

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

A `gs://` source the server has no credentials for can be presigned into an
`https://` URL ahead of time — see [Presigned `gs://` URLs](#presigned-gs-urls).

The transfer worker is a background thread of the server process, so **whatever
environment you launch `uvicorn` from is what every transfer uses**. Set source
credentials in that shell (or in `.env`, sourced as shown under *Run*), then
start the server from it. The values are read at process start, so restart the
server after refreshing an expiring credential.

### Credentials entered through the UI

For a deployment where the browser is the only input channel, the *Source
Credentials* panel accepts them at runtime instead:

| Provider | Fields | Applied to |
| --- | --- | --- |
| AWS | access key id, secret, optional session token, optional region | `s3://` |

Google Cloud is deliberately not in that list: no key file or bearer token is
accepted through the app. `gs://` sources are read with the server's own ADC, or
presigned into `https://` URLs beforehand — see below.

The *Cirro Connection* panel likewise takes the tenant host (`Use tenant`), so
`CIRRO_BASE_URL` need not be baked into the environment. Changing tenants
requires logging out first — the SDK client and its cached token are bound to
one tenant. Cirro's own auth is unchanged: the SDK's device-code login.

What this does and does not guarantee:

- **In memory only.** `backend/credentials.py` holds them in the process; they
  are never written to SQLite, never to disk, and never into log lines, error
  messages, or SSE events. A restart clears them — expect to re-enter after any
  reload, including `--reload` picking up a code change.
- **No read path.** `GET /credentials` returns presence plus a non-reversible
  hint (an access key id's last 4). The secrets cannot be read back out of the
  API.
- **Passed explicitly, not exported.** Values go to each `boto3`/`google-cloud`
  client call rather than into `os.environ`, so they cannot leak into
  subprocesses or race across worker threads.
- **Transport is your responsibility.** The form posts over whatever the app is
  served on. On anything other than `localhost`, terminate TLS in front of it —
  otherwise the secret crosses the network in cleartext. The panel shows a
  warning when it detects a non-local host over plain HTTP.
- Anything left unset falls back to the ambient chain, then to anonymous access
  for public objects — so a public-bucket migration needs no credentials at all.

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

S3 temporary (STS) credentials are read straight from the environment, either
exported directly or written to `.env` (see `.env.example`) and sourced:

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...
```

Prefer the native credential stores (`gcloud` ADC, `~/.aws`) over raw keys in
`.env`; short-lived STS values in `.env` are an acceptable dev exception since
they expire on their own. Note that `ftp://`/`sftp://` carry the password in
`source_location` — treat any plan CSV using them as a secret.

### Presigned `gs://` URLs

When the server has no Google credentials at all — the usual case for a
browser-only deployment — presign the plan instead of authenticating the app.
`scripts/gcs_presign.py` rewrites every `gs://` `source_location` in a
`file_plan.csv` into a signed `https://` URL that carries its own read
authorization; the rewritten plan loads into the app as-is and downloads through
the credential-free `https://` path.

```bash
gcloud auth application-default login
python scripts/gcs_presign.py testdata/file_plan.csv \
    -o testdata/file_plan_signed.csv \
    --impersonate-service-account transfer@PROJECT.iam.gserviceaccount.com \
    --expiration 30d --check
```

- Signing goes through IAM `signBlob` as the impersonated account, so no key
  file is needed anywhere: grant your own identity
  `roles/iam.serviceAccountTokenCreator` on that account, and the account read
  access to the data (`roles/storage.objectViewer`). Drop
  `--impersonate-service-account` only when ADC is itself a service account key.
  Each signature costs one IAM call, so raise `--workers` for a large plan.
- V2 signatures, so `--expiration` is not capped at the seven days V4 allows
  (default 30 days).
- `--check` fetches one byte through the first URL and aborts without writing if
  GCS refuses it — cheap insurance against emitting thousands of URLs that 403.
- The input can also be a bare list of `gs://` URIs, one per line (e.g. a
  `gcloud storage ls -r` dump); the output is then `gs_uri,source_location`.
- Every row of the output grants read access to that object until it expires.
  The file is written `0600` — treat it as a secret and keep it out of git.

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
