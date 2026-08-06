#!/usr/bin/env python3
"""Mint long-lived presigned https:// URLs for the gs:// objects in a file list.

The app holds no Google credentials: a `gs://` source is read with whatever
Application Default Credentials the server process happens to have, which is
nothing in a deployment where the browser is the only input channel. Presigning
moves that problem off the server — each URL carries its own authorization, and
the plan's `https://` downloader fetches it with no credentials at all.

Two input shapes, both written out as CSV:

    file_plan.csv   a plan table (any file with a `source_location` column) —
                    every column is preserved and each gs:// `source_location`
                    is replaced by its signed URL, so the result loads straight
                    into the app.
    URI list        one gs:// URI per line (e.g. a `gcloud storage ls -r`
                    dump) — written out as `gs_uri,source_location`.

Signing needs a service account's private key. Rather than handling a key file,
this signs through IAM signBlob as an impersonated account: grant your own
identity roles/iam.serviceAccountTokenCreator on that account, and the account
itself read access to the data.

    gcloud auth application-default login
    python scripts/gcs_presign.py testdata/file_plan.csv \
        -o testdata/file_plan_signed.csv \
        --impersonate-service-account transfer@PROJECT.iam.gserviceaccount.com \
        --expiration 30d --check

V2 signatures, not V4: V4 caps expiration at seven days, and these URLs have to
outlive a migration that runs for weeks. One consequence — a V2 signature
covers the HTTP verb, so a GET-signed URL rejects HEAD; the https downloader
already falls back to a ranged GET when HEAD fails.

The output is a bundle of bearer capabilities: anyone holding a URL can read
that object until it expires. It is written 0600 — keep it out of git.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import google.auth
from google.auth import impersonated_credentials
from google.auth.credentials import Signing
from google.auth.transport.requests import Request
from google.cloud import storage

# signBlob is authorized as the caller, on the cloud-platform scope; the
# impersonated account itself only ever needs to read objects.
CALLER_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
TARGET_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"

SOURCE_LOCATION = "source_location"
PROGRESS_EVERY = 200
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """'30d' / '12h' / '90m' / '3600' -> seconds."""
    unit = _DURATION_UNITS.get(text[-1:].lower())
    try:
        value = int(text[:-1] if unit else text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a duration: '{text}' (try 30d, 12h, 90m)")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"expiration must be positive, got '{text}'")
    return value * (unit or 1)


def normalize_header(header: str) -> str:
    """Canonicalize a CSV header, as backend/schema.py does (kept standalone)."""
    return re.sub(r"_+", "_", re.sub(r"[\s\-]+", "_", header.strip().lower()))


def read_input(path: Path) -> Tuple[List[str], List[Dict[str, str]], str]:
    """(fieldnames, rows, column) — the table to write back, and which column
    holds the source URI. A bare list of URIs becomes a two-column table."""
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    column = next(
        (name for name in reader.fieldnames or [] if normalize_header(name) == SOURCE_LOCATION),
        None,
    )
    if column is not None:
        return list(reader.fieldnames), list(reader), column
    uris = [line.strip() for line in text.splitlines() if line.strip()]
    return ["gs_uri", SOURCE_LOCATION], [{"gs_uri": u, SOURCE_LOCATION: u} for u in uris], SOURCE_LOCATION


def split_gs_uri(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if parsed.scheme != "gs" or not parsed.netloc or not key:
        raise ValueError(f"not a gs://bucket/object URI: '{uri}'")
    return parsed.netloc, key


def signing_credentials(impersonate: Optional[str]):
    """Credentials that can sign a URL, impersonating `impersonate` if given."""
    caller, _project = google.auth.default(scopes=[CALLER_SCOPE])
    if impersonate is None:
        if not isinstance(caller, Signing):
            raise ValueError(
                "these Application Default Credentials cannot sign URLs (no private "
                "key behind them) — pass --impersonate-service-account SA_EMAIL"
            )
        return caller
    # Every signature is one signBlob call made with the caller's own token.
    # Refresh it here so the concurrent signers below never race to refresh.
    caller.refresh(Request())
    return impersonated_credentials.Credentials(
        source_credentials=caller,
        target_principal=impersonate,
        target_scopes=[TARGET_SCOPE],
    )


def sign(client: storage.Client, uri: str, expires_at: datetime) -> str:
    bucket, key = split_gs_uri(uri)
    return client.bucket(bucket).blob(key).generate_signed_url(
        version="v2", expiration=expires_at
    )


def check_url(url: str) -> Optional[str]:
    """None if the URL serves bytes, else a description of the refusal."""
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=30):
            return None
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace").strip()
        return f"HTTP {exc.code} {exc.reason} — {body}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path,
                    help="file_plan.csv, or a file with one gs:// URI per line")
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="CSV to write (holds the signed URLs — treat as a secret)")
    ap.add_argument("--impersonate-service-account", metavar="SA_EMAIL",
                    help="service account to sign as, via IAM signBlob; omit only "
                         "when ADC is itself a service account key")
    ap.add_argument("--expiration", type=parse_duration, default="30d",
                    help="how long the URLs stay valid, e.g. 30d / 12h / 90m "
                         "(default 30d)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent signBlob calls (default 8)")
    ap.add_argument("--check", action="store_true",
                    help="fetch one byte through the first signed URL and abort "
                         "without writing if it is refused")
    args = ap.parse_args()

    fieldnames, rows, column = read_input(args.input)
    for row in rows:
        row[column] = (row.get(column) or "").strip()
    uris = sorted({row[column] for row in rows if row[column].startswith("gs://")})
    if not uris:
        print(f"{args.input}: no gs:// URIs found in '{column}'", file=sys.stderr)
        return 1
    passed_through = sum(1 for row in rows if not row[column].startswith("gs://"))

    try:
        credentials = signing_credentials(args.impersonate_service_account)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    # project=None is right here: signing is local to the bucket/object and
    # never calls the JSON API, so there is no project to bill or look up.
    client = storage.Client(credentials=credentials, project=None)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=args.expiration)
    print(f"signing {len(uris)} unique URIs as {credentials.signer_email}, "
          f"valid until {expires_at:%Y-%m-%d %H:%M} UTC", file=sys.stderr)

    signed: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        urls = pool.map(lambda uri: sign(client, uri, expires_at), uris)
        for n, (uri, url) in enumerate(zip(uris, urls), start=1):
            signed[uri] = url
            if n % PROGRESS_EVERY == 0 or n == len(uris):
                print(f"  signed {n}/{len(uris)}", file=sys.stderr)

    if args.check:
        failure = check_url(signed[uris[0]])
        if failure:
            print(f"check failed on {uris[0]}: {failure}", file=sys.stderr)
            print("nothing written", file=sys.stderr)
            return 1
        print(f"check ok: {uris[0]} serves bytes", file=sys.stderr)

    with args.output.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row[column] = signed.get(row[column], row[column])
            writer.writerow(row)
    args.output.chmod(0o600)  # a bundle of bearer capabilities

    print(f"wrote {len(rows)} rows: {len(uris)} signed URLs, "
          f"{passed_through} non-gs rows passed through")
    print(f"  -> {args.output}")
    print("Anyone holding a row can read that object until it expires — treat the "
          "output as a secret.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
