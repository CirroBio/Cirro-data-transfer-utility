from backend import cache, csv_loader, db, reconcile
from backend.models import Status

DATASETS = """name,data type,project
present,paired_dnaseq,ProjA
mismatch,paired_dnaseq,ProjA
absent,paired_dnaseq,ProjA
"""

FILES = """dataset,source uri,relative path,size
present,https://x/a,reads/a.txt,100
mismatch,https://x/b,reads/b.txt,100
absent,https://x/c,reads/c.txt,100
"""


class FakeDataset:
    def __init__(self, _id):
        self.id = _id


class FakeGateway:
    """Minimal stand-in exercising reconcile without a real Cirro connection."""

    def resolve_project_id(self, ref):
        return f"pid-{ref}"

    def find_dataset(self, project_id, name):
        if name == "absent":
            return None
        return FakeDataset(_id=f"ds-{name}")

    def list_dataset_files(self, dataset):
        if dataset.id == "ds-present":
            # Cirro reports the data/ prefix and a matching size.
            return [{"relative_path": "data/reads/a.txt", "size_bytes": 100}]
        if dataset.id == "ds-mismatch":
            return [{"relative_path": "data/reads/b.txt", "size_bytes": 999}]
        return []


def test_reconcile_classifies_present_mismatch_absent():
    csv_loader.persist(csv_loader.load(DATASETS, FILES))
    results = {r["name"]: r["status"] for r in reconcile.reconcile_all(FakeGateway())}
    assert results["present"] == Status.PRESENT
    assert results["mismatch"] == Status.MISMATCH
    assert results["absent"] == Status.PENDING

    # Statuses are persisted to the datasets table.
    with db.read() as conn:
        rows = {r["name"]: r["status"] for r in conn.execute("SELECT name,status FROM datasets")}
    assert rows["present"] == Status.PRESENT
    assert rows["mismatch"] == Status.MISMATCH


def test_reconcile_uses_cache_on_second_pass():
    csv_loader.persist(csv_loader.load(DATASETS, FILES))
    reconcile.reconcile_all(FakeGateway())
    cached = cache.get("pid-ProjA", "present")
    assert cached is not None
    assert cached["files"][0]["size_bytes"] == 100

    # A gateway that would explode if queried proves the cache is used.
    class Exploding(FakeGateway):
        def find_dataset(self, project_id, name):
            raise AssertionError("should not hit Cirro when cache is warm")

    results = {r["name"]: r["status"] for r in reconcile.reconcile_all(Exploding())}
    assert results["present"] == Status.PRESENT
