"""s3:// downloader (boto3). Falls back to anonymous access for public objects."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, NoCredentialsError

from backend.credentials import credentials
from backend.sources.base import Downloader, ProgressCb
from backend.sources.checksum import Checksum, MultiHasher, StatResult

_CHUNK = 1024 * 1024
_MD5_HEX = re.compile(r'^"?([0-9a-f]{32})"?$')

# S3 head_object exposes these when checksums were stored (base64 encoded).
_S3_CHECKSUM_FIELDS = {
    "ChecksumSHA256": "sha256",
    "ChecksumSHA1": "sha1",
    "ChecksumCRC32C": "crc32c",
    "ChecksumCRC32": "crc32",
    "ChecksumCRC64NVME": "crc64nvme",
}


def _split(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def _etag_is_md5(head: dict) -> bool:
    """Whether this object's ETag can be read as an MD5 of its contents.

    Not true under SSE-KMS or SSE-C: those ETags are unrelated to the plaintext
    digest (Cirro project buckets are KMS-encrypted, so this is the common
    case). SSE-S3 ('AES256') and unencrypted objects keep ETag == MD5.
    """
    return (head.get("ServerSideEncryption") != "aws:kms"
            and not head.get("SSECustomerAlgorithm"))


def _checksum_from_head(head: dict) -> Optional[Checksum]:
    for field, algo in _S3_CHECKSUM_FIELDS.items():
        if head.get(field):
            return Checksum.make(algo, head[field], encoding="base64")
    if not _etag_is_md5(head):
        return None
    etag = (head.get("ETag") or "").strip('"')
    m = _MD5_HEX.match(etag)
    if m:  # single-part upload -> ETag is the hex MD5
        return Checksum.make("md5", m.group(1), encoding="hex")
    return None


class S3Downloader(Downloader):
    schemes = {"s3"}

    def _client(self, anonymous: bool = False):
        if anonymous:
            return boto3.client("s3", config=BotoConfig(signature_version=UNSIGNED))
        # UI-supplied credentials win; with none set this is the ambient chain.
        return boto3.client("s3", **credentials.aws_client_kwargs())

    def _head(self, bucket: str, key: str) -> Tuple[dict, bool]:
        """Return (head, anonymous) trying signed first, then unsigned."""
        try:
            return self._client().head_object(
                Bucket=bucket, Key=key, ChecksumMode="ENABLED"
            ), False
        except (NoCredentialsError, ClientError):
            return self._client(anonymous=True).head_object(
                Bucket=bucket, Key=key, ChecksumMode="ENABLED"
            ), True

    def stat(self, uri: str) -> StatResult:
        bucket, key = _split(uri)
        head, _ = self._head(bucket, key)
        return StatResult(size=head.get("ContentLength"), checksum=_checksum_from_head(head))

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        bucket, key = _split(uri)
        _, anonymous = self._head(bucket, key)
        obj = self._client(anonymous=anonymous).get_object(Bucket=bucket, Key=key)
        body = obj["Body"]
        with dest.open("wb") as fh:
            while True:
                chunk = body.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                hasher.update(chunk)
                on_bytes(len(chunk))
