"""The input-table schema the utility consumes.

The migration plan is expressed as two CSV tables that together describe a
three-level hierarchy:

    Level 3  Folder    — cirro_folder_path, a tree rooted at the study
                         (the study IS the Cirro project; nested segments are
                         in-project folders).
    Level 2  Dataset   — one row in `dataset_plan` per target Cirro dataset,
                         typed by a Cirro ingest process (cirro_type_id).
    Level 1  File      — one row in `file_plan` per file that moves: a source
                         object placed at a relative path inside a dataset.

A dataset's identity is the pair (target_dataset_name, cirro_folder_path): the
same name recurs across folders within one study, so the name alone is not
unique. `dataset_key` folds that pair into the single string used as the
primary key throughout the app; `file_plan` joins to `dataset_plan` on the same
pair.

Header matching is tolerant of case, surrounding space, and space/hyphen vs
underscore, but the column *names* are the plan's own (target_dataset_name,
source_location, size_bytes, hash, ...) — this is the expected input format.
"""
from __future__ import annotations

import re
from typing import Dict, List

# ---- Level 2: dataset_plan columns --------------------------------------

# Present on every included dataset row.
DATASET_REQUIRED = ["target_dataset_name", "study", "cirro_folder_path", "status"]
# Present on included rows; blank on excluded rows (which have no Cirro target).
DATASET_OPTIONAL = [
    "source_kind", "source_dataset_id", "source_subpath",
    "cirro_type_id", "cirro_type_name",
    "n_files", "total_size_bytes", "total_size_human", "excluded_at",
]
DATASET_COLUMNS = DATASET_REQUIRED + DATASET_OPTIONAL

# ---- Level 1: file_plan columns -----------------------------------------

FILE_REQUIRED = [
    "target_dataset_name", "cirro_folder_path", "target_relative_path",
    "source_location", "size_bytes",
]
FILE_OPTIONAL = ["source_dataset_id", "source_subpath", "source_pathname", "hash"]
FILE_COLUMNS = FILE_REQUIRED + FILE_OPTIONAL

# The plan's `hash` column is a base64-encoded MD5 (as GCS advertises it).
HASH_ALGO = "md5"
HASH_ENCODING = "base64"

# dataset_plan.status values.
STATUS_INCLUDED = "included"
STATUS_EXCLUDED = "excluded"


def normalize_header(header: str) -> str:
    """Canonicalize a CSV header: 'Target Dataset-Name ' -> 'target_dataset_name'."""
    key = header.strip().lower()
    key = re.sub(r"[\s\-]+", "_", key)
    return re.sub(r"_+", "_", key)


def dataset_key(target_dataset_name: str, cirro_folder_path: str) -> str:
    """The single-string primary key for the (name, folder) pair.

    cirro_folder_path is always non-empty for an included dataset (it is rooted
    at the study), so this never collapses two datasets — the loader also
    asserts uniqueness defensively.
    """
    return f"{cirro_folder_path}/{target_dataset_name}"


def folder_in_project(study: str, cirro_folder_path: str) -> str:
    """The dataset's folder path *within its project*.

    The study is the project, and cirro_folder_path is rooted at the study, so
    the in-project folder is cirro_folder_path with the study prefix removed.
    A dataset at the study root ('pici0025' == study) has no in-project folder.
    """
    if cirro_folder_path == study:
        return ""
    prefix = study + "/"
    if cirro_folder_path.startswith(prefix):
        return cirro_folder_path[len(prefix):]
    return cirro_folder_path


def folder_tree(folders: List[str]) -> Dict[str, List[str]]:
    """Group full cirro_folder_paths by their study (first path segment).

    Returns {study: [folder_path, ...]} — the level-3 view used to organize
    datasets in the UI.
    """
    tree: Dict[str, List[str]] = {}
    for path in folders:
        study = path.split("/", 1)[0]
        tree.setdefault(study, [])
        if path not in tree[study]:
            tree[study].append(path)
    return tree
