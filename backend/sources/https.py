"""HTTPS / HTTP downloader (httpx)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import httpx

from backend.sources.base import Downloader, ProgressCb
from backend.sources.checksum import Checksum, MultiHasher, StatResult

_CHUNK = 1024 * 1024
_MD5_HEX = re.compile(r'^"?([0-9a-fA-F]{32})"?$')


def _checksum_from_headers(headers: httpx.Headers) -> Optional[Checksum]:
    # Content-MD5 is a base64-encoded MD5 (RFC 1864).
    content_md5 = headers.get("content-md5")
    if content_md5:
        return Checksum.make("md5", content_md5, encoding="base64")
    # A single-part S3 ETag is a hex MD5; a multipart ETag contains '-'.
    etag = headers.get("etag", "")
    m = _MD5_HEX.match(etag)
    if m:
        return Checksum.make("md5", m.group(1), encoding="hex")
    return None


class HttpsDownloader(Downloader):
    schemes = {"http", "https"}

    def stat(self, uri: str) -> StatResult:
        # Force identity so Content-Length matches the bytes we actually write
        # (a gzip'd response advertises the *compressed* length).
        headers = {"Accept-Encoding": "identity"}
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            resp = client.head(uri, headers=headers)
            if resp.status_code >= 400 or "content-length" not in resp.headers:
                # Some servers don't support HEAD; fall back to a ranged GET.
                resp = client.get(uri, headers={**headers, "Range": "bytes=0-0"})
            cr = resp.headers.get("content-range")
            if cr and "/" in cr:
                total = cr.rsplit("/", 1)[-1]
                length = int(total) if total.isdigit() else None
            else:
                cl = resp.headers.get("content-length")
                length = int(cl) if cl and cl.isdigit() else None
            # If the server compressed anyway, the length isn't the decoded size.
            if resp.headers.get("content-encoding"):
                length = None
            return StatResult(size=length, checksum=_checksum_from_headers(resp.headers))

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        with httpx.Client(follow_redirects=True, timeout=None) as client:
            with client.stream("GET", uri, headers={"Accept-Encoding": "identity"}) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(_CHUNK):
                        fh.write(chunk)
                        hasher.update(chunk)
                        on_bytes(len(chunk))
