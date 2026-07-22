import base64
import hashlib

from backend.sources.checksum import Checksum, MultiHasher, normalize_algo


def test_normalize_algo():
    assert normalize_algo("CRC-32C") == "crc32c"
    assert normalize_algo("MD-5") == "md5"
    assert normalize_algo("crc64") == "crc64nvme"
    assert normalize_algo("SHA256") == "sha256"


def test_hashlib_digests():
    data = b"the quick brown fox"
    h = MultiHasher(["md5", "sha256"])
    h.update(data)
    assert h.hex("md5") == hashlib.md5(data).hexdigest()
    assert h.hex("sha256") == hashlib.sha256(data).hexdigest()
    assert h.b64("md5") == base64.b64encode(hashlib.md5(data).digest()).decode()
    assert h.length == len(data)


def test_crc_digests_present():
    h = MultiHasher(["crc32c", "crc64nvme"])
    h.update(b"payload")
    # Just assert they produce stable, non-empty base64 of the right byte width.
    assert len(base64.b64decode(h.b64("crc32c"))) == 4
    assert len(base64.b64decode(h.b64("crc64nvme"))) == 8


def test_checksum_matches_hex_and_base64():
    data = b"hello world"
    h = MultiHasher(["md5"])
    h.update(data)
    hex_md5 = hashlib.md5(data).hexdigest()
    b64_md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
    assert Checksum.make("md5", hex_md5).matches(h)
    assert Checksum.make("md5", hex_md5.upper()).matches(h)  # hex case-insensitive
    assert Checksum.make("md5", b64_md5, "base64").matches(h)
    assert not Checksum.make("md5", "0" * 32).matches(h)
