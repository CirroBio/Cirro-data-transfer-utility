"""Maps a URI scheme to its Downloader and exposes module-level helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from backend.models import FileSpec
from backend.sources.base import Downloader, DownloadResult, ProgressCb
from backend.sources.checksum import StatResult
from backend.sources.ftp import FtpDownloader, SftpDownloader
from backend.sources.gcs import GcsDownloader
from backend.sources.https import HttpsDownloader
from backend.sources.s3 import S3Downloader
from backend.sources.synapse import SynapseDownloader

_DOWNLOADERS = [
    HttpsDownloader(),
    S3Downloader(),
    GcsDownloader(),
    FtpDownloader(),
    SftpDownloader(),
    SynapseDownloader(),
]

_REGISTRY: Dict[str, Downloader] = {
    scheme: d for d in _DOWNLOADERS for scheme in d.schemes
}


def scheme_of(uri: str) -> str:
    return (urlparse(uri).scheme or "").lower()


def get_downloader(uri: str) -> Downloader:
    scheme = scheme_of(uri)
    downloader = _REGISTRY.get(scheme)
    if downloader is None:
        raise ValueError(f"No downloader registered for scheme '{scheme}://' ({uri})")
    return downloader


def stat(uri: str) -> StatResult:
    return get_downloader(uri).stat(uri)


def download(spec: FileSpec, dest: Path, on_bytes: Optional[ProgressCb] = None) -> DownloadResult:
    return get_downloader(spec.source_uri).download(spec, dest, on_bytes)
