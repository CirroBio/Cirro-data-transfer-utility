"""Compare each dataset spec against what already exists in Cirro.

Result per dataset:
- PRESENT : a dataset with this name+folder exists in the study's project and
            its files (and sizes, when the plan supplies them) match.
- MISMATCH: it exists but the files/sizes differ.
- PENDING : not found in Cirro; ready to transfer.

The study is the Cirro project. Because a dataset name can recur across folders
within one project, the folder (recorded as a folder:// tag) disambiguates.
Cirro reports file paths under a ``data/`` prefix; spec paths don't carry it, so
we strip it before comparing.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from backend import cache, db
from backend.cirro_gateway import CirroGateway
from backend.models import Status
from backend.schema import folder_in_project


def _strip_data(path: str) -> str:
    return path[len("data/"):] if path.startswith("data/") else path


def _load_specs() -> List[Dict]:
    with db.read() as conn:
        datasets = conn.execute(
            "SELECT key, name, study, folder_path, status FROM datasets"
        ).fetchall()
        rows = []
        for d in datasets:
            files = conn.execute(
                "SELECT relative_path, expected_size FROM files WHERE dataset_key=?",
                (d["key"],),
            ).fetchall()
            rows.append(
                {
                    "key": d["key"],
                    "name": d["name"],
                    "study": d["study"],
                    "folder_path": d["folder_path"],
                    "status": d["status"],
                    "files": [
                        {"relative_path": f["relative_path"], "expected_size": f["expected_size"]}
                        for f in files
                    ],
                }
            )
    return rows


def _compare(spec_files: List[Dict], cirro_files: List[Dict]) -> bool:
    """True when every spec file is present in Cirro with a matching size
    (size only checked when the spec provides one)."""
    remote = {_strip_data(f["relative_path"]): f["size_bytes"] for f in cirro_files}
    spec_paths = {f["relative_path"] for f in spec_files}
    if spec_paths != set(remote):
        return False
    for f in spec_files:
        if f["expected_size"] is not None and remote.get(f["relative_path"]) != f["expected_size"]:
            return False
    return True


def _set_status(key: str, status: str) -> None:
    with db.write() as conn:
        conn.execute(
            "UPDATE datasets SET status=?, updated_at=datetime('now') WHERE key=?",
            (status, key),
        )


def reconcile_all(gateway: CirroGateway, default_project: Optional[str] = None) -> List[Dict]:
    """Reconcile every dataset in the DB against Cirro. Returns a summary list.
    Datasets already marked DONE are left as-is."""
    results = []
    for spec in _load_specs():
        key, name = spec["key"], spec["name"]

        def result(status: str, **extra) -> Dict:
            item = {"key": key, "name": name, "status": status, **extra}
            results.append(item)
            return item

        if spec["status"] == Status.DONE:
            result(Status.DONE)
            continue
        project_ref = spec["study"] or default_project
        if not project_ref:
            _set_status(key, Status.PENDING)
            result(Status.PENDING, note="no study/project")
            continue

        folder = folder_in_project(spec["study"], spec["folder_path"])
        project_id = gateway.resolve_project_id(project_ref)
        cached = cache.get(project_id, key)
        if cached is None:
            dataset = gateway.find_dataset(project_id, name, folder)
            if dataset is None:
                cache.put(project_id, key, None, [])
                cirro_files: List[Dict] = []
                dataset_id = None
            else:
                cirro_files = gateway.list_dataset_files(dataset)
                dataset_id = dataset.id
                cache.put(project_id, key, dataset_id, cirro_files)
        else:
            cirro_files = cached["files"]
            dataset_id = cached["dataset_id"]

        if not cirro_files and dataset_id is None:
            status = Status.PENDING
        else:
            status = Status.PRESENT if _compare(spec["files"], cirro_files) else Status.MISMATCH
        _set_status(key, status)
        result(status)
    return results
