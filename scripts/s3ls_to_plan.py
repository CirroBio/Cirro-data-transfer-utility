#!/usr/bin/env python3
"""Turn recursive `aws s3 ls` output into a dataset_plan.csv + file_plan.csv
pair that conforms to the utility's input schema (backend/schema.py).

The `aws s3 ls s3://<bucket>/<prefix> --recursive` output has one line per
object: "DATE TIME SIZE KEY" (the key may contain spaces). This tool expects
keys in Cirro's layout, datasets/<uuid>/data/<relative-path>, and treats each
top-level datasets/<uuid> as one dataset.

Streams the input line by line (the dump can be large). Directory-marker keys
(ending in '/') and keys with a hidden or underscore-prefixed path segment
(*/.* , */_*) are excluded; n_files / total_size_bytes are computed from what
survives, so the plan stays internally consistent.

Example:
    python scripts/s3ls_to_plan.py TEMP --bucket my-cirro-bucket --outdir testdata
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

DATA_MARKER = "/data/"  # datasets/<uuid>/data/<relative-path>


def human_bytes(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{n} B"
        v /= 1024
    return f"{n} B"


def parse_line(line: str):
    """Return (size, key) for a well-formed `aws s3 ls` line, else None."""
    line = line.rstrip("\n")
    if not line.strip():
        return None
    parts = line.split(None, 3)  # date, time, size, key (key keeps its spaces)
    if len(parts) < 4:
        return None
    _date, _time, size, key = parts
    try:
        return int(size), key
    except ValueError:
        return None


def split_key(key: str):
    """(uuid, relative_path) for datasets/<uuid>/data/<rel>, else None."""
    if not key.startswith("datasets/"):
        return None
    segs = key.split("/")
    if len(segs) < 4 or segs[2] != "data":
        return None
    uuid = segs[1]
    rel = key.split(f"datasets/{uuid}/data/", 1)[1]
    if not rel:  # the data/ marker itself
        return None
    return uuid, rel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="file with `aws s3 ls --recursive` output")
    ap.add_argument("--bucket", default="REPLACE_WITH_BUCKET",
                    help="S3 bucket the listing came from (for source_location s3:// URIs)")
    ap.add_argument("--outdir", type=Path, default=Path("testdata"))
    ap.add_argument("--folder", default="Data Transfer Testing/Batch A",
                    help="cirro_folder_path for every dataset; its first segment "
                         "is the study (== Cirro project)")
    ap.add_argument("--type-id", default="files",
                    help="cirro_type_id (must match a real ingest process to transfer)")
    ap.add_argument("--type-name", default="Files")
    ap.add_argument("--max-files", type=int, default=100,
                    help="keep at most this many files per dataset (default 100)")
    args = ap.parse_args()

    study = args.folder.split("/", 1)[0]

    # Per-dataset accumulation: uuid -> list of (rel, size, key)
    datasets: dict[str, list] = {}
    total_lines = skipped_dir = skipped_hidden = skipped_other = 0

    with args.input.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            total_lines += 1
            parsed = parse_line(line)
            if parsed is None:
                skipped_other += 1
                continue
            size, key = parsed
            if key.endswith("/"):
                skipped_dir += 1
                continue
            split = split_key(key)
            if split is None:
                skipped_other += 1
                continue
            uuid, rel = split
            if any(seg.startswith((".", "_")) for seg in rel.split("/")):
                skipped_hidden += 1
                continue
            datasets.setdefault(uuid, []).append((rel, size, key))

    if not datasets:
        print("No datasets found — is the input in datasets/<uuid>/data/ layout?",
              file=sys.stderr)
        return 1

    # Subsample with an even stride over the sorted paths, so a capped dataset
    # still spans the source tree instead of one alphabetical corner of it.
    for uuid, files in datasets.items():
        files.sort(key=lambda t: t[0])
        if len(files) > args.max_files:
            stride = -(-len(files) // args.max_files)
            datasets[uuid] = files[::stride][:args.max_files]

    args.outdir.mkdir(parents=True, exist_ok=True)
    dataset_plan = args.outdir / "dataset_plan.csv"
    file_plan = args.outdir / "file_plan.csv"

    with dataset_plan.open("w", newline="") as df, file_plan.open("w", newline="") as ff:
        dw = csv.writer(df)
        dw.writerow([
            "target_dataset_name", "study", "cirro_folder_path", "status",
            "source_kind", "source_dataset_id", "source_subpath",
            "cirro_type_id", "cirro_type_name",
            "n_files", "total_size_bytes", "total_size_human", "excluded_at",
        ])
        fw = csv.writer(ff)
        fw.writerow([
            "target_dataset_name", "cirro_folder_path", "source_dataset_id",
            "source_subpath", "target_relative_path", "source_pathname",
            "source_location", "size_bytes", "hash",
        ])

        names = {}
        for i, (uuid, files) in enumerate(sorted(datasets.items()), start=1):
            names[uuid] = name = f"Dataset {i}"
            n_files = len(files)
            total = sum(size for _rel, size, _key in files)
            dw.writerow([
                name, study, args.folder, "included",
                "s3_files", uuid, "",
                args.type_id, args.type_name,
                n_files, total, human_bytes(total), "",
            ])
            for rel, size, key in files:
                fw.writerow([
                    name, args.folder, uuid, "", rel, key.rsplit("/", 1)[-1],
                    f"s3://{args.bucket}/{key}", size, "",
                ])

    total_files = sum(len(f) for f in datasets.values())
    print(f"read {total_lines} lines")
    print(f"  excluded: {skipped_dir} dir-markers, {skipped_hidden} hidden/underscore, "
          f"{skipped_other} non-dataset/other")
    print(f"wrote {len(datasets)} datasets, {total_files} files into {args.folder}")
    for uuid, files in sorted(datasets.items()):
        print(f"  {names[uuid]}: {len(files)} files, "
              f"{human_bytes(sum(s for _r, s, _k in files))}")
        # Stripping this prefix off source_location yields target_relative_path.
        print(f"    root URI: s3://{args.bucket}/datasets/{uuid}/data/")
    print(f"  -> {dataset_plan}")
    print(f"  -> {file_plan}")
    if args.bucket == "REPLACE_WITH_BUCKET":
        print("\nNOTE: re-run with --bucket <name> so source_location URIs are real.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
