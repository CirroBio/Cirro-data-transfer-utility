"""The event stream transfer_dataset emits, which is all the UI has to go on."""
import pytest

from backend import db, transfer
from backend.models import Status
from backend.sources.base import DownloadResult

KEY = "p/f/d"
FILES = ["k0", "k1"]


class FakeGateway:
    """Every Cirro call the happy path makes, recorded rather than performed."""

    def __init__(self):
        self.uploaded = []
        self.verified = []

    def resolve_project_id(self, ref):
        return "proj"

    def resolve_process_id(self, ref):
        return "proc"

    def check_dataset_files(self, process_id, files, directory):
        pass

    def create_dataset(self, project_id, name, description, process_id, files, tags):
        return "ds-1"

    def checksum_method(self):
        return "CRC64NVME"

    def upload_files(self, project_id, dataset_id, directory, files, resume=False):
        self.uploaded.extend(files)

    def wait_for_ingest(self, project_id, dataset_id):
        return "COMPLETED"

    def validate_uploaded_files(self, project_id, dataset_id, directory, rel_paths,
                                on_verified=None):
        for done, rel in enumerate(rel_paths, start=1):
            self.verified.append(rel)
            if on_verified:
                on_verified(rel, done)
        return []


@pytest.fixture
def staged(monkeypatch):
    """A dataset in the DB whose files 'download' without touching the network."""
    with db.write() as conn:
        conn.execute(
            "INSERT INTO datasets (key, name, study, folder_path, data_type, status) "
            "VALUES (?, 'd', 'p', 'p/f', 'custom_dataset', ?)",
            (KEY, Status.PENDING),
        )
        for rel in FILES:
            conn.execute(
                "INSERT INTO files (dataset_key, source_uri, relative_path, expected_size) "
                "VALUES (?, ?, ?, 1)",
                (KEY, f"s3://b/{rel}", rel),
            )

    def download(spec, dest, on_bytes=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return DownloadResult(path=dest, size=1, verify_tier="size")

    monkeypatch.setattr(transfer.registry, "download", download)


def test_transfer_reports_every_phase_including_verify(staged):
    gateway = FakeGateway()
    events = []

    assert transfer.transfer_dataset(gateway, KEY, None, events.append) == Status.DONE

    assert [e["status"] for e in events if e["type"] == "dataset"] == [
        Status.VALIDATING, Status.DOWNLOADING, Status.UPLOADING, Status.VERIFYING,
        Status.DONE,
    ]
    assert gateway.uploaded == FILES
    assert gateway.verified == FILES


def test_verify_phase_is_never_silent(staged):
    # The phase runs for minutes on a large dataset. Without these events the
    # UI can only show a stalled bar, which reads as a hung transfer.
    events = []
    transfer.transfer_dataset(FakeGateway(), KEY, None, events.append)

    verify = [e for e in events if e.get("phase") == "verify"]
    # A count lands before the first file is verified (ingest waiting happens
    # inside this window), then one event per file.
    assert verify[0]["type"] == "progress"
    assert (verify[0]["done"], verify[0]["total"]) == (0, len(FILES))
    assert [(e["file"], e["done"], e["total"]) for e in verify[1:]] == [
        (rel, i, len(FILES)) for i, rel in enumerate(FILES, start=1)
    ]
