"""Dataclasses and status constants shared across the backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from backend.schema import dataset_key, folder_in_project


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
    CSV = "csv"        # matched a checksum supplied in the plan (file_plan.hash)
    SOURCE = "source"  # matched a checksum advertised by the source
    SIZE = "size"      # only the byte size was confirmed
    PATH = "path"      # nothing verifiable; path/existence only


@dataclass
class FileSpec:
    """Level 1 — a single file that moves (one file_plan row)."""
    source_uri: str            # file_plan.source_location
    relative_path: str         # file_plan.target_relative_path
    expected_size: Optional[int] = None       # file_plan.size_bytes
    expected_checksum: Optional[str] = None    # file_plan.hash
    checksum_type: Optional[str] = None
    checksum_encoding: str = "hex"             # 'hex' or 'base64'
    # Provenance carried through for traceability (not used to fetch).
    source_dataset_id: Optional[str] = None
    source_subpath: Optional[str] = None
    source_pathname: Optional[str] = None


@dataclass
class DatasetSpec:
    """Level 2 — a target Cirro dataset (one included dataset_plan row)."""
    name: str                  # dataset_plan.target_dataset_name
    study: str                 # dataset_plan.study — the Cirro project
    folder_path: str           # dataset_plan.cirro_folder_path (rooted at study)
    data_type: str             # dataset_plan.cirro_type_id (an ingest process)
    cirro_type_name: str = ""  # dataset_plan.cirro_type_name (display label)
    source_kind: Optional[str] = None
    source_dataset_id: Optional[str] = None
    source_subpath: Optional[str] = None
    planned_files: Optional[int] = None        # dataset_plan.n_files
    planned_bytes: Optional[int] = None        # dataset_plan.total_size_bytes
    description: str = ""
    files: List[FileSpec] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Unique primary key: the (name, folder) pair folded to one string."""
        return dataset_key(self.name, self.folder_path)

    @property
    def project_folder(self) -> str:
        """Folder path within the project (study prefix stripped)."""
        return folder_in_project(self.study, self.folder_path)

    def upload_tags(self) -> List[str]:
        """Tags applied to the created dataset. The in-project folder is
        recorded as a ``folder://`` marker so datasets keep their place in the
        study's folder tree."""
        folder = self.project_folder
        return [f"folder://{folder}"] if folder else []


@dataclass
class ExcludedDataset:
    """Level 2 — a source dataset the plan dropped (status == 'excluded').

    Has no Cirro target; recorded only so the excluded set stays visible.
    """
    study: str
    source_dataset_id: str
    source_kind: Optional[str] = None
    source_subpath: Optional[str] = None
    n_files: Optional[int] = None
    total_size_bytes: Optional[int] = None
    excluded_at: Optional[str] = None
