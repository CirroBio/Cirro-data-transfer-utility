import pytest

from backend import csv_loader, db
from backend.schema import dataset_key

# Two datasets share the name 'd1' but sit in different folders of one study —
# the (name, folder) pair is what makes them distinct. One excluded row.
DATASETS = """target_dataset_name,study,cirro_folder_path,status,source_kind,source_dataset_id,cirro_type_id,cirro_type_name,n_files,total_size_bytes,excluded_at
d1,pici0001,pici0001,included,gcs_files,pici0001/d1,aligned_bam,Aligned BAM,2,300,
d1,pici0001,pici0001/BatchB,included,gcs_files,pici0001/d1b,aligned_bam,Aligned BAM,1,100,
,pici0002,,excluded,gcs_files,pici0002/dropped,,,5,999,2026-06-24T14:00:00
"""

FILES = """target_dataset_name,cirro_folder_path,target_relative_path,source_location,size_bytes,hash
d1,pici0001,reads/a.bam,gs://b/a,100,eY3ptUR49/0i0fMjFBAaBQ==
d1,pici0001,reads/b.bam,gs://b/b,200,
d1,pici0001/BatchB,reads/a.bam,gs://b/c,100,
"""

KEY_TOP = dataset_key("d1", "pici0001")
KEY_NESTED = dataset_key("d1", "pici0001/BatchB")


def test_load_splits_included_excluded_and_keys_by_folder():
    included, excluded = csv_loader.load(DATASETS, FILES)
    keys = {s.key for s in included}
    assert keys == {KEY_TOP, KEY_NESTED}
    assert len(excluded) == 1
    assert excluded[0].source_dataset_id == "pici0002/dropped"
    assert excluded[0].n_files == 5
    assert excluded[0].excluded_at == "2026-06-24T14:00:00"


def test_folder_tag_is_relative_to_study():
    specs = {s.key: s for s in csv_loader.load(DATASETS, FILES)[0]}
    # Top-level dataset (folder == study) gets no folder tag.
    assert specs[KEY_TOP].upload_tags() == []
    # Nested dataset records the in-project folder.
    assert specs[KEY_NESTED].project_folder == "BatchB"
    assert specs[KEY_NESTED].upload_tags() == ["folder://BatchB"]


def test_hash_parsed_as_base64_md5():
    specs = {s.key: s for s in csv_loader.load(DATASETS, FILES)[0]}
    files = {f.relative_path: f for f in specs[KEY_TOP].files}
    a = files["reads/a.bam"]
    assert a.checksum_type == "md5"
    assert a.checksum_encoding == "base64"
    assert a.expected_checksum == "eY3ptUR49/0i0fMjFBAaBQ=="
    # A blank hash leaves no checksum to verify against.
    assert files["reads/b.bam"].expected_checksum is None
    assert files["reads/b.bam"].checksum_encoding == "hex"


def test_same_relative_path_allowed_across_folders():
    # Both d1 datasets have reads/a.bam; distinct datasets, so no collision.
    specs = {s.key: s for s in csv_loader.load(DATASETS, FILES)[0]}
    assert {f.relative_path for f in specs[KEY_NESTED].files} == {"reads/a.bam"}


def test_unknown_dataset_reference_flagged():
    files = FILES + "ghost,pici0001,x.bam,gs://b/x,1,\n"
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(DATASETS, files)
    assert "not present/included" in " ".join(exc.value.errors)


def test_duplicate_dataset_key_flagged():
    dup = DATASETS + "d1,pici0001,pici0001,included,gcs_files,x,aligned_bam,Aligned BAM,2,300,\n"
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(dup, FILES)
    assert "duplicate dataset" in " ".join(exc.value.errors)


def test_n_files_mismatch_flagged():
    # dataset_plan says n_files=2 for the top dataset; give it only 1 file row.
    files = """target_dataset_name,cirro_folder_path,target_relative_path,source_location,size_bytes,hash
d1,pici0001,reads/a.bam,gs://b/a,100,
d1,pici0001/BatchB,reads/a.bam,gs://b/c,100,
"""
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(DATASETS, files)
    errors = " ".join(exc.value.errors)
    assert "n_files=2 but 1 file rows" in errors


def test_unknown_type_flagged_against_processes():
    with pytest.raises(csv_loader.CsvError) as exc:
        csv_loader.load(DATASETS, FILES, known_processes={"some_other_process"})
    assert "unknown cirro_type_id 'aligned_bam'" in " ".join(exc.value.errors)


def test_persist_upserts_preserves_done_and_records_excluded():
    included, excluded = csv_loader.load(DATASETS, FILES)
    csv_loader.persist(included, excluded)
    with db.write() as conn:
        conn.execute("UPDATE datasets SET status='DONE' WHERE key=?", (KEY_TOP,))
    # Re-persist: the DONE row is left untouched, others refreshed.
    csv_loader.persist(included, excluded)
    with db.read() as conn:
        top = conn.execute("SELECT status FROM datasets WHERE key=?", (KEY_TOP,)).fetchone()
        assert top["status"] == "DONE"
        nfiles = conn.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        assert nfiles == 3
        nex = conn.execute("SELECT COUNT(*) n FROM excluded_datasets").fetchone()["n"]
        assert nex == 1
