"""Runtime configuration for the Cirro Data Transfer Utility.

All values can be overridden with environment variables so the app stays
usable in different environments without code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _data_dir() -> Path:
    """Directory that holds the SQLite DB and staging tempdirs.

    Defaults to ``~/.cirro-transfer`` but can be pointed elsewhere (e.g. a
    volume with plenty of space) via ``CIRRO_TRANSFER_HOME``.
    """
    root = os.environ.get("CIRRO_TRANSFER_HOME")
    path = Path(root).expanduser() if root else Path.home() / ".cirro-transfer"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Config:
    # Cirro tenant to talk to (host only, no scheme) — matches the SDK convention.
    base_url: str = os.environ.get("CIRRO_BASE_URL", "app.cirro.bio")
    # Where SQLite + staging live.
    home: Path = _data_dir()
    # Number of datasets transferred concurrently. Serial (1) by default.
    concurrency: int = int(os.environ.get("CIRRO_TRANSFER_CONCURRENCY", "1"))

    @property
    def db_path(self) -> Path:
        return self.home / "transfer.db"

    @property
    def staging_root(self) -> Path:
        path = self.home / "staging"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def tmp_root(self) -> Path:
        """Scratch space for anything that would otherwise land in ``/tmp``.

        Kept under ``home`` so a deployment only has to size and mount one
        directory; ``app`` points ``tempfile`` here at startup.
        """
        path = self.home / "tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def frontend_dist(self) -> Path:
        # backend/config.py -> repo root -> frontend/dist
        return Path(__file__).resolve().parent.parent / "frontend" / "dist"


config = Config()
