"""Synapse (syn://) downloader — interface stub only.

Wiring this up requires the ``synapseclient`` package and an auth token; the
methods raise a clear error until that work is done. The scheme is registered
so the app surfaces a helpful message instead of an opaque "unknown scheme".
"""
from __future__ import annotations

from pathlib import Path

from backend.sources.base import Downloader, ProgressCb
from backend.sources.checksum import MultiHasher, StatResult

_MSG = (
    "Synapse (syn://) transfers are not implemented yet. Install synapseclient "
    "and provide a Synapse auth token, then implement SynapseDownloader.stat/"
    "_stream using synapseclient.Synapse().get(entity, downloadFile=...)."
)


class SynapseDownloader(Downloader):
    schemes = {"syn"}

    def stat(self, uri: str) -> StatResult:
        raise NotImplementedError(_MSG)

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        raise NotImplementedError(_MSG)
