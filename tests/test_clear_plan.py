from fastapi.testclient import TestClient

from backend import db
from backend.app import app
from backend.models import Status

client = TestClient(app)


def _load_one_dataset():
    with db.write() as conn:
        conn.execute(
            "INSERT INTO datasets (key, name, study, folder_path, data_type, status) "
            "VALUES ('p/f/d', 'd', 'p', 'p/f', 'custom_dataset', ?)",
            (Status.DONE,),
        )
        conn.execute(
            "INSERT INTO files (dataset_key, source_uri, relative_path) "
            "VALUES ('p/f/d', 's3://b/k', 'k')"
        )
        conn.execute("INSERT INTO queue (dataset_key, state) VALUES ('p/f/d', 'QUEUED')")


def test_clear_plan_empties_every_table():
    _load_one_dataset()
    removed = db.clear_plan()
    assert removed == {"files": 1, "datasets": 1, "excluded_datasets": 0, "queue": 1}
    with db.read() as conn:
        for table in ("datasets", "files", "queue"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_delete_datasets_endpoint_reports_counts():
    _load_one_dataset()
    res = client.delete("/datasets")
    assert res.status_code == 200
    assert res.json()["cleared"]["datasets"] == 1
    assert client.get("/datasets").json() == []


def test_delete_datasets_refused_while_a_transfer_runs():
    _load_one_dataset()
    with db.write() as conn:
        conn.execute("UPDATE queue SET state='RUNNING' WHERE dataset_key='p/f/d'")
    res = client.delete("/datasets")
    assert res.status_code == 409
    assert "transfer is running" in res.json()["detail"]
    # The plan survives a refused clear.
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
