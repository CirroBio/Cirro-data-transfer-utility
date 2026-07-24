"""Per-dataset transfer worker: the state machine from the plan.

PENDING -> VALIDATING -> DOWNLOADING -> UPLOADING -> VERIFYING -> DONE

The dataset's study is the Cirro project; its folder (recorded as a folder://
tag) places it within that project. Datasets are addressed by their key (the
(name, folder) pair), since a name can recur across folders.

Resume-correctness note: we do NOT use ``project.upload_dataset()`` (it always
creates a new dataset and never resumes). Instead we create the dataset via the
low-level client and persist its id BEFORE uploading, so an interrupted upload
can be resumed with ``upload_files(resume=True)`` (which skips already-uploaded
files by size). VERIFYING then checksum-confirms every file, guarding the
size-only resume skip.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backend import cache, db
from backend.config import config
from backend.cirro_gateway import CirroGateway
from backend.models import Status
from backend.sources import registry

Emit = Callable[[Dict], None]


def _safe_dirname(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _load(key: str) -> Optional[Dict]:
    with db.read() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        files = conn.execute(
            "SELECT * FROM files WHERE dataset_key=? ORDER BY relative_path", (key,)
        ).fetchall()
    ds = dict(row)
    ds["files"] = [dict(f) for f in files]
    return ds


def _set_status(key: str, status: str, error: Optional[str] = None) -> None:
    with db.write() as conn:
        conn.execute(
            "UPDATE datasets SET status=?, error=?, updated_at=datetime('now') WHERE key=?",
            (status, error, key),
        )


def _set_dataset_id(key: str, dataset_id: str) -> None:
    with db.write() as conn:
        conn.execute("UPDATE datasets SET dataset_id=? WHERE key=?", (dataset_id, key))


def _update_file(key: str, rel: str, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.write() as conn:
        conn.execute(
            f"UPDATE files SET {cols} WHERE dataset_key=? AND relative_path=?",
            (*fields.values(), key, rel),
        )


def transfer_dataset(
    gateway: CirroGateway, key: str, default_project: Optional[str], emit: Emit
) -> str:
    """Run one dataset end-to-end. Returns the final status. Never raises —
    failures are recorded as FAILED and returned."""
    ds = _load(key)
    if ds is None:
        return Status.FAILED
    name = ds["name"]

    def status(new: str, **extra) -> None:
        _set_status(key, new, error=extra.get("error"))
        emit({"type": "dataset", "key": key, "name": name, "status": new, **extra})

    try:
        project_ref = ds["study"] or default_project
        if not project_ref:
            raise ValueError("No study/project set for this dataset")
        project_id = gateway.resolve_project_id(project_ref)
        process_id = gateway.resolve_process_id(ds["data_type"])

        rel_paths: List[str] = [f["relative_path"] for f in ds["files"]]
        staging = config.staging_root / _safe_dirname(key)
        staging.mkdir(parents=True, exist_ok=True)

        # --- VALIDATING: fail fast on the process's naming rules -----------
        status(Status.VALIDATING)
        gateway.check_dataset_files(process_id, rel_paths, str(staging))

        # --- DOWNLOADING ---------------------------------------------------
        status(Status.DOWNLOADING)
        for f in ds["files"]:
            rel = f["relative_path"]
            dest = staging / rel
            _update_file(key, rel, status=Status.DOWNLOADING, downloaded_bytes=0)

            state = {"n": 0}

            def on_bytes(delta: int, rel=rel, state=state, f=f) -> None:
                state["n"] += delta
                emit({
                    "type": "progress", "key": key, "name": name, "phase": "download",
                    "file": rel, "bytes": state["n"], "total": f["expected_size"],
                })

            result = registry.download(
                registry_spec(f), dest, on_bytes  # type: ignore[arg-type]
            )
            _update_file(
                key, rel, status="DONE", downloaded_bytes=result.size,
                verify_tier=result.verify_tier,
            )

        # --- create (persist id BEFORE upload) or resume -------------------
        dataset_id = ds["dataset_id"]
        resume = False
        skip_upload = False
        if dataset_id:
            try:
                cirro_status = gateway.dataset_status(project_id, dataset_id)
                if cirro_status == "PENDING":
                    resume = True  # interrupted upload — continue it
                else:
                    skip_upload = True  # already finalized (e.g. retry after verify)
            except Exception:  # noqa: BLE001 - stale id, start fresh
                dataset_id = None
        if not dataset_id:
            tags = json.loads(ds["tags_json"] or "[]")
            dataset_id = gateway.create_dataset(
                project_id, name, ds["description"] or "", process_id, rel_paths, tags
            )
            _set_dataset_id(key, dataset_id)

        # --- UPLOADING (S3 verifies CRC64NVME server-side) -----------------
        status(Status.UPLOADING, checksum_method=gateway.checksum_method())
        if not skip_upload:
            _upload(gateway, project_id, dataset_id, staging, rel_paths, resume, key, name, emit)

        # --- VERIFYING (end-to-end checksum confirmation) ------------------
        status(Status.VERIFYING)
        size_only = gateway.validate_uploaded_files(project_id, dataset_id, staging, rel_paths)
        if size_only:
            emit({"type": "warning", "key": key, "name": name,
                  "message": f"{len(size_only)} file(s) verified by size only (no remote checksum)"})

        # --- DONE ----------------------------------------------------------
        cache.invalidate(project_id, key)
        shutil.rmtree(staging, ignore_errors=True)
        status(Status.DONE, dataset_id=dataset_id)
        return Status.DONE

    except Exception as exc:  # noqa: BLE001 - reported to the UI, worker continues
        status(Status.FAILED, error=str(exc))
        return Status.FAILED


def _upload(
    gateway: CirroGateway,
    project_id: str,
    dataset_id: str,
    staging: Path,
    rel_paths: List[str],
    resume: bool,
    key: str,
    name: str,
    emit: Emit,
) -> None:
    total = len(rel_paths)
    if resume:
        # One call; the SDK skips files already uploaded (by size).
        emit({"type": "progress", "key": key, "name": name, "phase": "upload",
              "resume": True, "total": total})
        gateway.upload_files(project_id, dataset_id, str(staging), rel_paths, resume=True)
        emit({"type": "progress", "key": key, "name": name, "phase": "upload",
              "done": total, "total": total})
        return
    # Fresh upload: drive file-by-file so we can report per-file completion.
    for i, rel in enumerate(rel_paths, start=1):
        gateway.upload_files(project_id, dataset_id, str(staging), [rel], resume=False)
        emit({"type": "progress", "key": key, "name": name, "phase": "upload",
              "file": rel, "done": i, "total": total})


def registry_spec(file_row: Dict):
    """Adapt a files-table row into a FileSpec for the downloader."""
    from backend.models import FileSpec

    return FileSpec(
        source_uri=file_row["source_uri"],
        relative_path=file_row["relative_path"],
        expected_size=file_row["expected_size"],
        expected_checksum=file_row["expected_checksum"],
        checksum_type=file_row["checksum_type"],
        checksum_encoding=file_row["checksum_encoding"],
        source_dataset_id=file_row["source_dataset_id"],
        source_subpath=file_row["source_subpath"],
        source_pathname=file_row["source_pathname"],
    )
