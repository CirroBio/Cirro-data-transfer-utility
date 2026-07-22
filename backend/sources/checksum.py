"""Streaming, multi-algorithm checksum computation.

Different sources advertise integrity in different algorithms and encodings
(S3 ETag = hex MD5, GCS = base64 MD5 / base64 CRC32C, Cirro = base64
CRC64NVME). ``MultiHasher`` computes every algorithm we might need in a single
pass over the bytes, so download verification never re-reads the file.
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Set

_HASHLIB = {"md5", "sha1", "sha256"}
_CRC = {"crc32", "crc32c", "crc64nvme"}


def normalize_algo(name: str) -> str:
    """Canonicalize an algorithm name: 'CRC-32C' -> 'crc32c', 'MD-5' -> 'md5'."""
    key = re.sub(r"[^a-z0-9]", "", name.strip().lower())
    if key in ("crc64", "crc64nvme"):
        return "crc64nvme"
    return key


def _crc_func(name: str):
    from awscrt import checksums

    return {
        "crc32": checksums.crc32,
        "crc32c": checksums.crc32c,
        "crc64nvme": checksums.crc64nvme,
    }[name]


class MultiHasher:
    def __init__(self, algos: Iterable[str]):
        self.algos: Set[str] = {normalize_algo(a) for a in algos if a}
        self._hl = {a: hashlib.new(a) for a in self.algos if a in _HASHLIB}
        self._crc = {a: 0 for a in self.algos if a in _CRC}
        self._crc_funcs = {a: _crc_func(a) for a in self._crc}
        self.length = 0

    def update(self, chunk: bytes) -> None:
        self.length += len(chunk)
        for h in self._hl.values():
            h.update(chunk)
        for a in self._crc:
            self._crc[a] = self._crc_funcs[a](chunk, self._crc[a])

    def _crc_bytes(self, algo: str) -> bytes:
        width = 8 if algo == "crc64nvme" else 4
        return self._crc[algo].to_bytes(width, "big")

    def hex(self, algo: str) -> str:
        algo = normalize_algo(algo)
        if algo in self._hl:
            return self._hl[algo].hexdigest()
        return self._crc_bytes(algo).hex()

    def b64(self, algo: str) -> str:
        algo = normalize_algo(algo)
        if algo in self._hl:
            return base64.b64encode(self._hl[algo].digest()).decode()
        return base64.b64encode(self._crc_bytes(algo)).decode()


@dataclass(frozen=True)
class Checksum:
    """A checksum advertised by a source or supplied in the CSV."""
    algo: str          # normalized algorithm name
    value: str         # expected digest
    encoding: str = "hex"  # 'hex' or 'base64'

    @classmethod
    def make(cls, algo: str, value: str, encoding: str = "hex") -> "Checksum":
        return cls(normalize_algo(algo), value.strip(), encoding)

    def matches(self, hasher: MultiHasher) -> bool:
        if self.encoding == "base64":
            return self.value == hasher.b64(self.algo)
        return self.value.lower() == hasher.hex(self.algo).lower()


@dataclass(frozen=True)
class StatResult:
    size: Optional[int] = None
    checksum: Optional[Checksum] = None
