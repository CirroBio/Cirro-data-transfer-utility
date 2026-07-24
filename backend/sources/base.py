"""Downloader abstract base + the shared download-verification ladder."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Set

from backend.models import FileSpec, VerifyTier
from backend.sources.checksum import Checksum, MultiHasher, StatResult

# Called with the number of bytes written since the last call.
ProgressCb = Callable[[int], None]


class ChecksumMismatch(Exception):
    pass


class SizeMismatch(Exception):
    pass


@dataclass
class DownloadResult:
    path: Path
    size: int
    verify_tier: str


class Downloader(ABC):
    """One implementation per URI scheme."""

    #: URI schemes this downloader handles, e.g. {"s3"}.
    schemes: Set[str] = set()

    @abstractmethod
    def stat(self, uri: str) -> StatResult:
        """Return the remote size and, if advertised, a checksum. Never raises
        for a missing checksum — only for an unreachable/absent object."""

    @abstractmethod
    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        """Stream the object into ``dest`` while feeding ``hasher`` every chunk."""

    def download(
        self,
        spec: FileSpec,
        dest: Path,
        on_bytes: Optional[ProgressCb] = None,
    ) -> DownloadResult:
        """Download ``spec.source_uri`` to ``dest`` and verify integrity via the
        ladder: CSV checksum -> source checksum -> size -> path-only. Raises on
        any mismatch."""
        on_bytes = on_bytes or (lambda _n: None)
        stat = self.stat(spec.source_uri)

        csv_ck = (
            Checksum.make(
                spec.checksum_type or "md5",
                spec.expected_checksum,
                encoding=getattr(spec, "checksum_encoding", None) or "hex",
            )
            if spec.expected_checksum and spec.checksum_type
            else None
        )

        # Compute exactly the algorithms we may need to verify against.
        needed: Set[str] = set()
        if csv_ck:
            needed.add(csv_ck.algo)
        if stat.checksum:
            needed.add(stat.checksum.algo)
        hasher = MultiHasher(needed)

        dest.parent.mkdir(parents=True, exist_ok=True)
        self._stream(spec.source_uri, dest, hasher, on_bytes)

        tier = self._verify(spec, stat, csv_ck, hasher, dest)
        return DownloadResult(path=dest, size=hasher.length, verify_tier=tier)

    @staticmethod
    def _verify(
        spec: FileSpec,
        stat: StatResult,
        csv_ck: Optional[Checksum],
        hasher: MultiHasher,
        dest: Path,
    ) -> str:
        actual_size = hasher.length
        # Size is a cheap sanity check applied whenever it's known.
        expected_size = spec.expected_size if spec.expected_size is not None else stat.size
        if expected_size is not None and expected_size != actual_size:
            raise SizeMismatch(
                f"{spec.source_uri}: expected {expected_size} bytes, got {actual_size}"
            )

        if csv_ck:
            if not csv_ck.matches(hasher):
                raise ChecksumMismatch(
                    f"{spec.source_uri}: CSV {csv_ck.algo} checksum mismatch"
                )
            return VerifyTier.CSV
        if stat.checksum:
            if not stat.checksum.matches(hasher):
                raise ChecksumMismatch(
                    f"{spec.source_uri}: source {stat.checksum.algo} checksum mismatch"
                )
            return VerifyTier.SOURCE
        if expected_size is not None:
            return VerifyTier.SIZE
        return VerifyTier.PATH
