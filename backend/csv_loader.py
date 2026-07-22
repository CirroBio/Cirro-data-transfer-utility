"""Parse and validate the two driving CSVs into DatasetSpec/FileSpec, and
persist them into SQLite.

The parser is tolerant of header spelling (case, spaces, underscores) so users
don't have to match an exact template. Validation is collected into a list of
human-readable errors rather than raising on the first problem.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Dict, Iterable, List, Optional, Tuple

from backend import db
from backend.models import DatasetSpec, FileSpec, Status


class CsvError(Exception):
    """Raised when the CSVs cannot be loaded; carries all collected errors."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _norm(header: str) -> str:
    return header.strip().lower().replace("_", " ")


def _rows(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    fieldmap = {name: _norm(name) for name in reader.fieldnames}
    out: List[Dict[str, str]] = []
    for raw in reader:
        row = {}
        for key, value in raw.items():
            if key is None:
                continue
            row[fieldmap[key]] = (value or "").strip()
        out.append(row)
    return out


def _get(row: Dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def _split_tags(value: str) -> List[str]:
    return [t.strip() for t in value.split(";") if t.strip()]


def parse_datasets(text: str, errors: List[str]) -> Dict[str, DatasetSpec]:
    specs: Dict[str, DatasetSpec] = {}
    for i, row in enumerate(_rows(text), start=2):  # header is line 1
        name = _get(row, "name")
        data_type = _get(row, "data type", "datatype", "process")
        if not name:
            errors.append(f"datasets.csv line {i}: missing 'name'")
            continue
        if not data_type:
            errors.append(f"datasets.csv line {i} ({name}): missing 'data type'")
        if name in specs:
            errors.append(f"datasets.csv line {i}: duplicate dataset name '{name}'")
            continue
        specs[name] = DatasetSpec(
            name=name,
            data_type=data_type,
            description=_get(row, "description"),
            project=_get(row, "project") or None,
            folder_path=_get(row, "folder path", "folder") or None,
            tags=_split_tags(_get(row, "tags")),
        )
    return specs


def _parse_size(value: str, where: str, errors: List[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(f"{where}: size '{value}' is not an integer")
        return None


def parse_files(
    text: str, datasets: Dict[str, DatasetSpec], errors: List[str]
) -> None:
    seen: set[Tuple[str, str]] = set()
    for i, row in enumerate(_rows(text), start=2):
        where = f"files.csv line {i}"
        dataset = _get(row, "dataset", "dataset name")
        uri = _get(row, "source uri", "uri", "source")
        rel = _get(row, "relative path", "path")
        if not dataset:
            errors.append(f"{where}: missing 'dataset'")
            continue
        if dataset not in datasets:
            errors.append(f"{where}: references unknown dataset '{dataset}'")
            continue
        if not uri:
            errors.append(f"{where} ({dataset}): missing 'source uri'")
            continue
        if not rel:
            errors.append(f"{where} ({dataset}): missing 'relative path'")
            continue
        key = (dataset, rel)
        if key in seen:
            errors.append(f"{where}: duplicate relative path '{rel}' in '{dataset}'")
            continue
        seen.add(key)
        datasets[dataset].files.append(
            FileSpec(
                source_uri=uri,
                relative_path=rel,
                expected_size=_parse_size(row.get("size", ""), f"{where} ({dataset})", errors),
                expected_checksum=_get(row, "checksum") or None,
                checksum_type=(_get(row, "checksum type", "checksumtype") or None),
            )
        )


def load(
    datasets_csv: str,
    files_csv: str,
    known_processes: Optional[Iterable[str]] = None,
) -> List[DatasetSpec]:
    """Parse both CSVs, validate, and return the specs.

    ``known_processes`` (names and/or ids of ingest processes) is used to flag
    unknown data types when the Cirro client is connected; pass None to skip.
    Raises CsvError with all collected problems if anything is invalid.
    """
    errors: List[str] = []
    datasets = parse_datasets(datasets_csv, errors)
    parse_files(files_csv, datasets, errors)

    for spec in datasets.values():
        if not spec.files:
            errors.append(f"dataset '{spec.name}' has no files")

    if known_processes is not None:
        known = set(known_processes)
        for spec in datasets.values():
            if spec.data_type and spec.data_type not in known:
                errors.append(
                    f"dataset '{spec.name}': unknown data type '{spec.data_type}' "
                    f"(not an available ingest process)"
                )

    if errors:
        raise CsvError(errors)
    return list(datasets.values())


def persist(specs: List[DatasetSpec]) -> None:
    """Upsert specs into SQLite. Existing DONE/PRESENT rows are left untouched
    so a reload doesn't wipe completed transfer state."""
    with db.write() as conn:
        for spec in specs:
            existing = conn.execute(
                "SELECT status FROM datasets WHERE name = ?", (spec.name,)
            ).fetchone()
            if existing and existing["status"] in (Status.DONE, Status.PRESENT):
                continue
            conn.execute(
                """
                INSERT INTO datasets (name, project, data_type, description,
                                      folder_path, tags_json, status)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                ON CONFLICT(name) DO UPDATE SET
                    project=excluded.project,
                    data_type=excluded.data_type,
                    description=excluded.description,
                    folder_path=excluded.folder_path,
                    tags_json=excluded.tags_json
                """,
                (
                    spec.name, spec.project, spec.data_type, spec.description,
                    spec.folder_path, json.dumps(spec.tags),
                ),
            )
            conn.execute("DELETE FROM files WHERE dataset_name = ?", (spec.name,))
            for f in spec.files:
                conn.execute(
                    """
                    INSERT INTO files (dataset_name, source_uri, relative_path,
                                       expected_size, expected_checksum, checksum_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.name, f.source_uri, f.relative_path, f.expected_size,
                        f.expected_checksum, f.checksum_type,
                    ),
                )
