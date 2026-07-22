"""Dataclasses and status constants shared across the backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class Status:
    """Dataset transfer statuses (also stored verbatim in SQLite)."""
    PENDING = "PENDING"        # not yet in Cirro; ready to transfer
    VALIDATING = "VALIDATING"  # checking naming rules against the ingest process
    DOWNLOADING = "DOWNLOADING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"    # comparing finalized Cirro checksums to local files
    DONE = "DONE"
    PRESENT = "PRESENT"        # already in Cirro and validated
    MISMATCH = "MISMATCH"      # in Cirro but files/sizes differ from the spec
    FAILED = "FAILED"

    # Statuses an in-flight worker may leave behind after a crash.
    IN_FLIGHT = {VALIDATING, DOWNLOADING, UPLOADING, VERIFYING}
    # Statuses eligible to be (re)enqueued for transfer.
    TRANSFERABLE = {PENDING, MISMATCH, FAILED}


# Verification tiers, strongest first — recorded per file so the UI can show
# how each file's integrity was confirmed.
class VerifyTier:
    CSV = "csv"        # matched a checksum supplied in the CSV
    SOURCE = "source"  # matched a checksum advertised by the source
    SIZE = "size"      # only the byte size was confirmed
    PATH = "path"      # nothing verifiable; path/existence only


@dataclass
class FileSpec:
    source_uri: str
    relative_path: str
    expected_size: Optional[int] = None
    expected_checksum: Optional[str] = None
    checksum_type: Optional[str] = None


@dataclass
class DatasetSpec:
    name: str
    data_type: str
    description: str = ""
    project: Optional[str] = None
    folder_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    files: List[FileSpec] = field(default_factory=list)

    def upload_tags(self) -> List[str]:
        """Tags applied to the created dataset, including the folder:// marker."""
        tags = list(self.tags)
        if self.folder_path:
            tags.append(f"folder://{self.folder_path}")
        return tags
