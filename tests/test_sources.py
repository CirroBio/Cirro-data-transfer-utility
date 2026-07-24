import base64
import hashlib
from pathlib import Path

import pytest

from backend.models import FileSpec, VerifyTier
from backend.sources.base import ChecksumMismatch, Downloader, SizeMismatch
from backend.sources.checksum import Checksum, MultiHasher, StatResult
from backend.sources.registry import get_downloader
from backend.sources.synapse import SynapseDownloader


class FakeDownloader(Downloader):
    """Serves in-memory bytes so the ladder can be tested without a network."""

    schemes = {"fake"}

    def __init__(self, payload: bytes, checksum: StatResult = None):
        self.payload = payload
        self._stat = checksum or StatResult(size=len(payload))

    def stat(self, uri):
        return self._stat

    def _stream(self, uri, dest: Path, hasher: MultiHasher, on_bytes):
        with dest.open("wb") as fh:
            fh.write(self.payload)
        hasher.update(self.payload)
        on_bytes(len(self.payload))


def _spec(**kw):
    return FileSpec(source_uri="fake://x", relative_path="f", **kw)


def test_tier_csv_wins(tmp_path):
    data = b"abc123"
    d = FakeDownloader(data)
    md5 = hashlib.md5(data).hexdigest()
    res = d.download(_spec(expected_checksum=md5, checksum_type="md5"), tmp_path / "f")
    assert res.verify_tier == VerifyTier.CSV


def test_tier_csv_base64_md5(tmp_path):
    # file_plan.hash is a base64-encoded MD5; the ladder must honor the encoding.
    data = b"abc123"
    d = FakeDownloader(data)
    b64 = base64.b64encode(hashlib.md5(data).digest()).decode()
    res = d.download(
        _spec(expected_checksum=b64, checksum_type="md5", checksum_encoding="base64"),
        tmp_path / "f",
    )
    assert res.verify_tier == VerifyTier.CSV


def test_tier_source_when_no_csv(tmp_path):
    data = b"abc123"
    src_ck = Checksum.make("md5", hashlib.md5(data).hexdigest())
    d = FakeDownloader(data, StatResult(size=len(data), checksum=src_ck))
    res = d.download(_spec(), tmp_path / "f")
    assert res.verify_tier == VerifyTier.SOURCE


def test_tier_size_then_path(tmp_path):
    data = b"abc123"
    d = FakeDownloader(data, StatResult(size=len(data)))
    assert d.download(_spec(), tmp_path / "f").verify_tier == VerifyTier.SIZE

    d2 = FakeDownloader(data, StatResult(size=None))
    assert d2.download(_spec(), tmp_path / "g").verify_tier == VerifyTier.PATH


def test_bad_csv_checksum_raises(tmp_path):
    d = FakeDownloader(b"abc123")
    with pytest.raises(ChecksumMismatch):
        d.download(_spec(expected_checksum="0" * 32, checksum_type="md5"), tmp_path / "f")


def test_size_mismatch_raises(tmp_path):
    d = FakeDownloader(b"abc123", StatResult(size=999))
    with pytest.raises(SizeMismatch):
        d.download(_spec(), tmp_path / "f")


def test_registry_scheme_dispatch():
    assert get_downloader("s3://bucket/key").__class__.__name__ == "S3Downloader"
    assert get_downloader("gs://bucket/key").__class__.__name__ == "GcsDownloader"
    assert get_downloader("https://h/p").__class__.__name__ == "HttpsDownloader"
    with pytest.raises(ValueError):
        get_downloader("weird://x")


def test_synapse_stub_raises_clearly(tmp_path):
    with pytest.raises(NotImplementedError) as exc:
        SynapseDownloader().stat("syn://123")
    assert "not implemented" in str(exc.value).lower()
