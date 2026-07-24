"""Parse and validate the two plan tables into specs, and persist to SQLite.

Input format (see backend/schema.py):

- dataset_plan.csv (level 2): one row per target Cirro dataset. Rows with
  status='included' become transferable datasets; status='excluded' rows have
  no Cirro target and are recorded separately for visibility.
- file_plan.csv (level 1): one row per file that moves. Joined to its dataset
  on (target_dataset_name, cirro_folder_path).

Header spelling is tolerated (case, spaces, hyphen vs underscore); the column
names are the plan's own. Validation collects all problems into a list rather
than raising on the first.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Dict, Iterable, List, Optional, Tuple

from backend import db, schema
from backend.models import DatasetSpec, ExcludedDataset, FileSpec, Status


class CsvError(Exception):
    """Raised when the tables cannot be loaded; carries all collected errors."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _rows(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    fieldmap = {name: schema.normalize_header(name) for name in reader.fieldnames}
    out: List[Dict[str, str]] = []
    for raw in reader:
        row: Dict[str, str] = {}
        for key, value in raw.items():
            if key is None:
                continue
            row[fieldmap[key]] = (value or "").strip()
        out.append(row)
    return out


def _require_columns(rows: List[Dict[str, str]], required: List[str], table: str,
                     errors: List[str]) -> bool:
    if not rows:
        errors.append(f"{table}: no rows")
        return False
    present = set(rows[0].keys())
    missing = [c for c in required if c not in present]
    if missing:
        errors.append(f"{table}: missing required column(s): {', '.join(missing)}")
        return False
    return True


def _parse_int(value: str, where: str, errors: List[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(f"{where}: '{value}' is not an integer")
        return None


def parse_datasets(
    text: str, errors: List[str]
) -> Tuple[Dict[str, DatasetSpec], List[ExcludedDataset]]:
    """Return (included specs keyed by dataset_key, excluded records)."""
    included: Dict[str, DatasetSpec] = {}
    excluded: List[ExcludedDataset] = []
    rows = _rows(text)
    if not _require_columns(rows, schema.DATASET_REQUIRED, "dataset_plan.csv", errors):
        return included, excluded

    for i, row in enumerate(rows, start=2):  # header is line 1
        where = f"dataset_plan.csv line {i}"
        status = row.get("status", "")
        if status == schema.STATUS_EXCLUDED:
            excluded.append(
                ExcludedDataset(
                    study=row.get("study", ""),
                    source_dataset_id=row.get("source_dataset_id", ""),
                    source_kind=row.get("source_kind") or None,
                    source_subpath=row.get("source_subpath") or None,
                    n_files=_parse_int(row.get("n_files", ""), where, errors),
                    total_size_bytes=_parse_int(row.get("total_size_bytes", ""), where, errors),
                    excluded_at=row.get("excluded_at") or None,
                )
            )
            continue
        if status != schema.STATUS_INCLUDED:
            errors.append(f"{where}: unknown status '{status}'")
            continue

        name = row.get("target_dataset_name", "")
        folder = row.get("cirro_folder_path", "")
        study = row.get("study", "")
        if not name:
            errors.append(f"{where}: included row missing 'target_dataset_name'")
            continue
        if not study:
            errors.append(f"{where} ({name}): missing 'study'")
        if not folder:
            errors.append(f"{where} ({name}): missing 'cirro_folder_path'")
            continue

        spec = DatasetSpec(
            name=name,
            study=study,
            folder_path=folder,
            data_type=row.get("cirro_type_id", ""),
            cirro_type_name=row.get("cirro_type_name", ""),
            source_kind=row.get("source_kind") or None,
            source_dataset_id=row.get("source_dataset_id") or None,
            source_subpath=row.get("source_subpath") or None,
            planned_files=_parse_int(row.get("n_files", ""), where, errors),
            planned_bytes=_parse_int(row.get("total_size_bytes", ""), where, errors),
        )
        if not spec.data_type:
            errors.append(f"{where} ({name}): missing 'cirro_type_id'")
        if spec.key in included:
            errors.append(
                f"{where}: duplicate dataset (name, folder) = ('{name}', '{folder}')"
            )
            continue
        included[spec.key] = spec
    return included, excluded


def parse_files(
    text: str, datasets: Dict[str, DatasetSpec], errors: List[str]
) -> None:
    rows = _rows(text)
    if not _require_columns(rows, schema.FILE_REQUIRED, "file_plan.csv", errors):
        return
    seen: set[Tuple[str, str]] = set()
    for i, row in enumerate(rows, start=2):
        where = f"file_plan.csv line {i}"
        name = row.get("target_dataset_name", "")
        folder = row.get("cirro_folder_path", "")
        uri = row.get("source_location", "")
        rel = row.get("target_relative_path", "")
        if not name or not folder:
            errors.append(f"{where}: missing 'target_dataset_name'/'cirro_folder_path'")
            continue
        key = schema.dataset_key(name, folder)
        if key not in datasets:
            errors.append(
                f"{where}: references dataset ('{name}', '{folder}') "
                f"not present/included in dataset_plan.csv"
            )
            continue
        if not uri:
            errors.append(f"{where} ({name}): missing 'source_location'")
            continue
        if not rel:
            errors.append(f"{where} ({name}): missing 'target_relative_path'")
            continue
        dedup = (key, rel)
        if dedup in seen:
            errors.append(f"{where}: duplicate target path '{rel}' in dataset '{name}'")
            continue
        seen.add(dedup)

        hashval = row.get("hash", "")
        datasets[key].files.append(
            FileSpec(
                source_uri=uri,
                relative_path=rel,
                expected_size=_parse_int(row.get("size_bytes", ""), f"{where} ({name})", errors),
                expected_checksum=hashval or None,
                checksum_type=schema.HASH_ALGO if hashval else None,
                checksum_encoding=schema.HASH_ENCODING if hashval else "hex",
                source_dataset_id=row.get("source_dataset_id") or None,
                source_subpath=row.get("source_subpath") or None,
                source_pathname=row.get("source_pathname") or None,
            )
        )


def load(
    dataset_plan_csv: str,
    file_plan_csv: str,
    known_processes: Optional[Iterable[str]] = None,
) -> Tuple[List[DatasetSpec], List[ExcludedDataset]]:
    """Parse both plan tables, validate, and return (included, excluded).

    ``known_processes`` (names and/or ids of ingest processes) flags unknown
    cirro_type_ids when the Cirro client is connected; pass None to skip.
    Raises CsvError with all collected problems if anything is invalid.
    """
    errors: List[str] = []
    datasets, excluded = parse_datasets(dataset_plan_csv, errors)
    parse_files(file_plan_csv, datasets, errors)

    for spec in datasets.values():
        if not spec.files:
            errors.append(
                f"dataset ('{spec.name}', '{spec.folder_path}') is included but "
                f"has no files in file_plan.csv"
            )
        elif spec.planned_files is not None and spec.planned_files != len(spec.files):
            errors.append(
                f"dataset '{spec.name}': n_files={spec.planned_files} but "
                f"{len(spec.files)} file rows found"
            )

    if known_processes is not None:
        known = set(known_processes)
        for spec in datasets.values():
            if spec.data_type and spec.data_type not in known:
                errors.append(
                    f"dataset '{spec.name}': unknown cirro_type_id '{spec.data_type}' "
                    f"(not an available ingest process)"
                )

    if errors:
        raise CsvError(errors)
    return list(datasets.values()), excluded


def persist(specs: List[DatasetSpec], excluded: Optional[List[ExcludedDataset]] = None) -> None:
    """Upsert specs into SQLite. Existing DONE/PRESENT rows are left untouched
    so a reload doesn't wipe completed transfer state."""
    with db.write() as conn:
        for spec in specs:
            existing = conn.execute(
                "SELECT status FROM datasets WHERE key = ?", (spec.key,)
            ).fetchone()
            if existing and existing["status"] in (Status.DONE, Status.PRESENT):
                continue
            conn.execute(
                """
                INSERT INTO datasets (key, name, study, folder_path, data_type,
                    cirro_type_name, source_kind, source_dataset_id, source_subpath,
                    planned_files, planned_bytes, description, tags_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                ON CONFLICT(key) DO UPDATE SET
                    name=excluded.name,
                    study=excluded.study,
                    folder_path=excluded.folder_path,
                    data_type=excluded.data_type,
                    cirro_type_name=excluded.cirro_type_name,
                    source_kind=excluded.source_kind,
                    source_dataset_id=excluded.source_dataset_id,
                    source_subpath=excluded.source_subpath,
                    planned_files=excluded.planned_files,
                    planned_bytes=excluded.planned_bytes,
                    description=excluded.description,
                    tags_json=excluded.tags_json
                """,
                (
                    spec.key, spec.name, spec.study, spec.folder_path, spec.data_type,
                    spec.cirro_type_name, spec.source_kind, spec.source_dataset_id,
                    spec.source_subpath, spec.planned_files, spec.planned_bytes,
                    spec.description, json.dumps(spec.upload_tags()),
                ),
            )
            conn.execute("DELETE FROM files WHERE dataset_key = ?", (spec.key,))
            for f in spec.files:
                conn.execute(
                    """
                    INSERT INTO files (dataset_key, source_uri, relative_path,
                        expected_size, expected_checksum, checksum_type, checksum_encoding,
                        source_dataset_id, source_subpath, source_pathname)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.key, f.source_uri, f.relative_path, f.expected_size,
                        f.expected_checksum, f.checksum_type, f.checksum_encoding,
                        f.source_dataset_id, f.source_subpath, f.source_pathname,
                    ),
                )

        for ex in excluded or []:
            conn.execute(
                """
                INSERT INTO excluded_datasets (study, source_dataset_id, source_kind,
                    source_subpath, n_files, total_size_bytes, excluded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(study, source_dataset_id) DO UPDATE SET
                    source_kind=excluded.source_kind,
                    source_subpath=excluded.source_subpath,
                    n_files=excluded.n_files,
                    total_size_bytes=excluded.total_size_bytes,
                    excluded_at=excluded.excluded_at
                """,
                (
                    ex.study, ex.source_dataset_id, ex.source_kind, ex.source_subpath,
                    ex.n_files, ex.total_size_bytes, ex.excluded_at,
                ),
            )
