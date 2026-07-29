import pytest

from backend import db, transfer
from backend.models import Status
from backend.queue import TransferQueue


def _dataset(key="p/f/d", n_files=2):
    with db.write() as conn:
        conn.execute(
            "INSERT INTO datasets (key, name, study, folder_path, data_type, status) "
            "VALUES (?, 'd', 'p', 'p/f', 'custom_dataset', ?)",
            (key, Status.PENDING),
        )
        for i in range(n_files):
            conn.execute(
                "INSERT INTO files (dataset_key, source_uri, relative_path, expected_size) "
                "VALUES (?, ?, ?, 1)",
                (key, f"s3://b/k{i}", f"k{i}"),
            )


def test_cancel_drops_a_queued_dataset_before_it_starts():
    _dataset()
    with db.write() as conn:
        conn.execute("INSERT INTO queue (dataset_key, state) VALUES ('p/f/d', 'QUEUED')")

    result = TransferQueue().cancel(["p/f/d"])

    assert result == {"dropped": ["p/f/d"], "stopping": []}
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0] == 0
        assert (
            conn.execute("SELECT status FROM datasets WHERE key='p/f/d'").fetchone()[0]
            == Status.CANCELLED
        )


def test_cancel_flags_a_running_dataset_rather_than_dropping_it():
    _dataset()
    with db.write() as conn:
        conn.execute("INSERT INTO queue (dataset_key, state) VALUES ('p/f/d', 'RUNNING')")

    queue = TransferQueue()
    result = queue.cancel(["p/f/d"])

    assert result == {"dropped": [], "stopping": ["p/f/d"]}
    assert queue.is_cancelled("p/f/d")
    # The row stays so the worker can finish its current file and clean up.
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0] == 1


def test_cancel_ignores_keys_that_are_not_queued():
    _dataset()
    assert TransferQueue().cancel(["p/f/d", "nope"]) == {"dropped": [], "stopping": []}


def test_transfer_stops_before_touching_cirro_when_cancelled_upfront():
    _dataset()

    class ExplodingGateway:
        def resolve_project_id(self, ref):
            raise AssertionError("cancelled transfer must not reach Cirro")

    events = []
    status = transfer.transfer_dataset(
        ExplodingGateway(), "p/f/d", None, events.append, is_cancelled=lambda: True
    )

    assert status == Status.CANCELLED
    assert [e["status"] for e in events] == [Status.CANCELLED]
    with db.read() as conn:
        assert (
            conn.execute("SELECT status FROM datasets WHERE key='p/f/d'").fetchone()[0]
            == Status.CANCELLED
        )


def test_cancelled_is_transferable_so_it_can_be_resumed():
    assert Status.CANCELLED in Status.TRANSFERABLE


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_cancel_all_covers_every_queue_state(state):
    _dataset()
    with db.write() as conn:
        conn.execute("INSERT INTO queue (dataset_key, state) VALUES ('p/f/d', ?)", (state,))
    result = TransferQueue().cancel(["p/f/d"])
    assert len(result["dropped"]) + len(result["stopping"]) == 1
