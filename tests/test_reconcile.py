from backend import csv_loader, reconcile
from backend.models import Status
from backend.schema import dataset_key

# Three datasets in one study (= project pici0001). 'dup' appears in two folders
# to exercise folder-aware matching. Study is the project, so no default needed.
DATASETS = """target_dataset_name,study,cirro_folder_path,status,cirro_type_id,n_files,total_size_bytes
present,pici0001,pici0001,included,aligned_bam,1,100
mismatch,pici0001,pici0001,included,aligned_bam,1,100
absent,pici0001,pici0001,included,aligned_bam,1,100
dup,pici0001,pici0001/A,included,aligned_bam,1,100
dup,pici0001,pici0001/B,included,aligned_bam,1,100
"""

FILES = """target_dataset_name,cirro_folder_path,target_relative_path,source_location,size_bytes
present,pici0001,reads/a.txt,gs://x/a,100
mismatch,pici0001,reads/b.txt,gs://x/b,100
absent,pici0001,reads/c.txt,gs://x/c,100
dup,pici0001/A,reads/a.txt,gs://x/da,100
dup,pici0001/B,reads/b.txt,gs://x/db,100
"""

KEY_DUP_A = dataset_key("dup", "pici0001/A")
KEY_DUP_B = dataset_key("dup", "pici0001/B")


class FakeDataset:
    def __init__(self, _id, folder=""):
        self.id = _id
        self.tags = [type("T", (), {"value": f"folder://{folder}"})()] if folder else []


class FakeGateway:
    """Minimal stand-in exercising reconcile without a real Cirro connection."""

    def resolve_project_id(self, ref):
        return f"pid-{ref}"

    def find_dataset(self, project_id, name, folder=""):
        if name == "absent":
            return None
        if name == "dup":
            # Two 'dup' datasets exist, one per folder — return the match.
            return FakeDataset(_id=f"ds-dup-{folder}", folder=folder)
        return FakeDataset(_id=f"ds-{name}", folder=folder)

    def list_dataset_files(self, dataset):
        if dataset.id == "ds-present":
            return [{"relative_path": "data/reads/a.txt", "size_bytes": 100}]
        if dataset.id == "ds-mismatch":
            return [{"relative_path": "data/reads/b.txt", "size_bytes": 999}]
        if dataset.id == "ds-dup-A":
            return [{"relative_path": "data/reads/a.txt", "size_bytes": 100}]
        if dataset.id == "ds-dup-B":
            return [{"relative_path": "data/reads/b.txt", "size_bytes": 100}]
        return []


def test_reconcile_classifies_present_mismatch_absent():
    included, _ = csv_loader.load(DATASETS, FILES)
    csv_loader.persist(included)
    results = {r["key"]: r["status"] for r in reconcile.reconcile_all(FakeGateway())}
    assert results[dataset_key("present", "pici0001")] == Status.PRESENT
    assert results[dataset_key("mismatch", "pici0001")] == Status.MISMATCH
    assert results[dataset_key("absent", "pici0001")] == Status.PENDING


def test_reconcile_disambiguates_same_name_by_folder():
    included, _ = csv_loader.load(DATASETS, FILES)
    csv_loader.persist(included)
    results = {r["key"]: r["status"] for r in reconcile.reconcile_all(FakeGateway())}
    # Both 'dup' datasets match the file-list of their own folder → PRESENT.
    assert results[KEY_DUP_A] == Status.PRESENT
    assert results[KEY_DUP_B] == Status.PRESENT


def test_reconcile_requeries_cirro_every_pass():
    """Reconcile reports the tenant's current state, so it must not serve a
    remembered answer — a dataset created or changed outside this app has to
    show up on the next pass."""
    included, _ = csv_loader.load(DATASETS, FILES)
    csv_loader.persist(included)

    class Counting(FakeGateway):
        def __init__(self):
            self.lookups = 0

        def find_dataset(self, project_id, name, folder=""):
            self.lookups += 1
            return super().find_dataset(project_id, name, folder)

    first = Counting()
    reconcile.reconcile_all(first)
    assert first.lookups == 5

    # 'absent' now exists in Cirro, matching its plan; a second pass must notice.
    class NowPresent(Counting):
        def find_dataset(self, project_id, name, folder=""):
            self.lookups += 1
            if name == "absent":
                return FakeDataset(_id="ds-absent-now")
            return FakeGateway.find_dataset(self, project_id, name, folder)

        def list_dataset_files(self, dataset):
            if dataset.id == "ds-absent-now":
                return [{"relative_path": "data/reads/c.txt", "size_bytes": 100}]
            return super().list_dataset_files(dataset)

    second = NowPresent()
    results = {r["key"]: r["status"] for r in reconcile.reconcile_all(second)}
    assert second.lookups == 5
    assert results[dataset_key("absent", "pici0001")] == Status.PRESENT
