import pytest

from backend import csv_loader, db

DATASETS = """name,description,project,data type,folder path,tags
d1,demo one,ProjA,paired_dnaseq,/nfs/run1,teamX;cohort1
d2,demo two,ProjB,paired_dnaseq,,
"""

FILES = """dataset,source uri,relative path,size,checksum,checksum type
d1,https://example.com/a.txt,reads/a.txt,100,,
d1,s3://bucket/b.txt,reads/b.txt,,d41d8cd98f00b204e9800998ecf8427e,md5
d2,gs://bucket/c.txt,c.txt,,,
"""


def test_load_and_folder_tag():
    specs = {s.name: s for s in csv_loader.load(DATASETS, FILES)}
    assert set(specs) == {"d1", "d2"}
    assert specs["d1"].upload_tags() == ["teamX", "cohort1", "folder:///nfs/run1"]
    assert specs["d2"].upload_tags() == []  # no folder path -> no folder:// tag
    assert len(specs["d1"].files) == 2
    assert specs["d1"].files[0].expected_size == 100
    assert specs["d1"].files[1].checksum_type == "md5"


def test_unknown_dataset_and_missing_fields():
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(
            "name,data type\n,paired\n",
            "dataset,source uri,relative path\nghost,https://x,y\n",
        )
    errors = " ".join(exc.value.errors)
    assert "missing 'name'" in errors
    assert "unknown dataset 'ghost'" in errors


def test_duplicate_dataset_and_path():
    dup_ds = "name,data type\nd1,paired\nd1,paired\n"
    dup_files = (
        "dataset,source uri,relative path\n"
        "d1,https://x/a,reads/a\n"
        "d1,https://x/a2,reads/a\n"
    )
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(dup_ds, dup_files)
    errors = " ".join(exc.value.errors)
    assert "duplicate dataset name" in errors
    assert "duplicate relative path" in errors


def test_unknown_data_type_flagged_against_processes():
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(DATASETS, FILES, known_processes={"some_other_process"})
    assert "unknown data type 'paired_dnaseq'" in " ".join(exc.value.errors)


def test_persist_upserts_and_preserves_done():
    specs = csv_loader.load(DATASETS, FILES)
    csv_loader.persist(specs)
    with db.write() as conn:
        conn.execute("UPDATE datasets SET status='DONE' WHERE name='d1'")
    # Re-persist: DONE row must be left untouched, others refreshed.
    csv_loader.persist(specs)
    with db.read() as conn:
        d1 = conn.execute("SELECT status FROM datasets WHERE name='d1'").fetchone()
        assert d1["status"] == "DONE"
        nfiles = conn.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        assert nfiles == 3
