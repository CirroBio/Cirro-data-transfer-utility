"""FTP and SFTP downloaders. Neither protocol advertises a checksum, so
verification falls back to size (when known) or path-only."""
from __future__ import annotations

import ftplib
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from backend.sources.base import Downloader, ProgressCb
from backend.sources.checksum import MultiHasher, StatResult

_CHUNK = 1024 * 1024


def _creds(parsed) -> tuple[str, str]:
    user = unquote(parsed.username) if parsed.username else "anonymous"
    password = unquote(parsed.password) if parsed.password else "anonymous@"
    return user, password


class FtpDownloader(Downloader):
    schemes = {"ftp"}

    def _connect(self, uri: str) -> tuple[ftplib.FTP, str]:
        parsed = urlparse(uri)
        user, password = _creds(parsed)
        ftp = ftplib.FTP()
        ftp.connect(parsed.hostname, parsed.port or 21, timeout=30)
        ftp.login(user, password)
        return ftp, unquote(parsed.path)

    def stat(self, uri: str) -> StatResult:
        ftp, path = self._connect(uri)
        try:
            try:
                ftp.sendcmd("TYPE I")  # SIZE needs binary mode
                size: Optional[int] = ftp.size(path)
            except ftplib.all_errors:
                size = None
            return StatResult(size=size, checksum=None)
        finally:
            ftp.close()

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        ftp, path = self._connect(uri)
        try:
            with dest.open("wb") as fh:
                def _cb(chunk: bytes) -> None:
                    fh.write(chunk)
                    hasher.update(chunk)
                    on_bytes(len(chunk))

                ftp.retrbinary(f"RETR {path}", _cb, blocksize=_CHUNK)
        finally:
            ftp.close()


class SftpDownloader(Downloader):
    schemes = {"sftp"}

    def _connect(self, uri: str):
        import paramiko

        parsed = urlparse(uri)
        transport = paramiko.Transport((parsed.hostname, parsed.port or 22))
        user, password = _creds(parsed)
        transport.connect(username=user, password=None if password == "anonymous@" else password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        return transport, sftp, unquote(parsed.path)

    def stat(self, uri: str) -> StatResult:
        transport, sftp, path = self._connect(uri)
        try:
            return StatResult(size=sftp.stat(path).st_size, checksum=None)
        finally:
            sftp.close()
            transport.close()

    def _stream(self, uri: str, dest: Path, hasher: MultiHasher, on_bytes: ProgressCb) -> None:
        transport, sftp, path = self._connect(uri)
        try:
            with sftp.open(path, "rb") as src, dest.open("wb") as fh:
                src.prefetch()
                while True:
                    chunk = src.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    hasher.update(chunk)
                    on_bytes(len(chunk))
        finally:
            sftp.close()
            transport.close()
