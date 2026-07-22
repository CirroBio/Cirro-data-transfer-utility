"""gs:// downloader (google-cloud-storage). Falls back to an anonymous client."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from backend.sources.base import Downloader, ProgressCb
from backend.sources.checksum import Checksum, MultiHasher, StatResult

_CHUNK = 1024 * 1024


def _split(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def _checksum_from_blob(blob) -> Optional[Checksum]:
    # GCS exposes base64-encoded MD5 and CRC32C. CRC32C is always present and
    # covers composite objects, so prefer it; fall back to MD5.
    if getattr(blob, "crc32c", None):
        return Checksum.make("crc32c", blob.crc32c, encoding="base64")
    if getattr(blob, "md5_hash", None):
        return Checksum.make("md5", blob.md5_hash, encoding="base64")
    return None


class GcsDownloader(Downloader):
    schemes = {"gs"}

    def _bucket(self, bucket_name: str):
        from google.cloud import storage
        from google.auth.exceptions import DefaultCredentialsError

        try:
            client = storage.Client()
        except (DefaultCredentialsError, EnvironmentError):
            client = storage.Client.create_anonymous_client()
        return client.bucket(bucket_name)

    def _get_blob(self, uri: str):
        bucket_name, key = _split(uri)
        blob = self._bucket(bucket_name).get_blob(key)
        if blob is None:
            raise FileNotFoundError(f"GCS object not found: {uri}")
        return blob

    def stat(self, uri: str) -> StatResult:
        blob = self._get_blob(uri)
        return StatResult(size=blob.size, checksum=_checksum_from_blob(blob))

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        blob = self._get_blob(uri)
        with blob.open("rb") as src, dest.open("wb") as fh:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                hasher.update(chunk)
                on_bytes(len(chunk))
