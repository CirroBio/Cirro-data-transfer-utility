from pathlib import Path

import pytest
from cirro_api_client.v1.errors import UnexpectedStatus

from backend import cirro_gateway
from backend.cirro_gateway import CirroGateway, _retry_throttled


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Backoff delays would otherwise make these tests take ~30s."""
    monkeypatch.setattr(cirro_gateway.time, "sleep", lambda _s: None)


def _throttle():
    return UnexpectedStatus(429, b'{"message":"Too Many Requests"}')


def test_retries_until_it_succeeds():
    calls = []

    def call():
        calls.append(1)
        if len(calls) < 3:
            raise _throttle()
        return "ok"

    assert _retry_throttled(call) == "ok"
    assert len(calls) == 3


def test_gives_up_after_the_backoff_is_exhausted():
    attempts = []

    def call():
        attempts.append(1)
        raise _throttle()

    with pytest.raises(UnexpectedStatus):
        _retry_throttled(call)
    assert len(attempts) == len(cirro_gateway._THROTTLE_BACKOFF) + 1


def test_other_statuses_are_not_retried():
    attempts = []

    def call():
        attempts.append(1)
        raise UnexpectedStatus(500, b"boom")

    with pytest.raises(UnexpectedStatus):
        _retry_throttled(call)
    assert len(attempts) == 1


def _gateway_with_statuses(monkeypatch, statuses):
    gateway = CirroGateway(base_url="test")
    seen = iter(statuses)
    monkeypatch.setattr(
        CirroGateway, "dataset_status", lambda self, p, d: next(seen)
    )
    return gateway


def test_wait_for_ingest_polls_until_settled(monkeypatch):
    gateway = _gateway_with_statuses(
        monkeypatch, ["PENDING", "PENDING", "COMPLETED"]
    )
    assert gateway.wait_for_ingest("p", "d") == "COMPLETED"


def test_wait_for_ingest_raises_on_failed_ingest(monkeypatch):
    gateway = _gateway_with_statuses(monkeypatch, ["PENDING", "FAILED"])
    with pytest.raises(ValueError, match="ingest failed"):
        gateway.wait_for_ingest("p", "d")


def test_wait_for_ingest_times_out(monkeypatch):
    gateway = _gateway_with_statuses(monkeypatch, ["PENDING"] * 100)
    clock = iter([0] + [cirro_gateway._INGEST_TIMEOUT_SECONDS + 1] * 10)
    monkeypatch.setattr(cirro_gateway.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="still PENDING"):
        gateway.wait_for_ingest("p", "d")


class _FakeFile:
    """A Cirro file as the SDK hands it over: paths carry the `data/` prefix."""

    def __init__(self, rel: str, size: int, checksum: bool = True):
        self.relative_path = f"data/{rel}"
        self.size_bytes = size
        self._checksum = checksum

    def validate(self, local_path: str) -> None:
        if not self._checksum:
            raise RuntimeWarning("no remote checksum")


class _FakeDataset:
    def __init__(self, files):
        self.files = files
        self.listings = 0

    def list_files(self):
        self.listings += 1
        return self.files


def _gateway_for(monkeypatch, dataset):
    gateway = CirroGateway(base_url="test")
    project = type("P", (), {"get_dataset_by_id": lambda self, _id: dataset})()
    portal = type("Portal", (), {"get_project_by_id": lambda self, _id: project})()
    monkeypatch.setattr(CirroGateway, "_require_portal", lambda self: portal)
    return gateway


def test_verification_lists_the_dataset_once(monkeypatch):
    # get_file() would re-fetch the whole manifest per file, so a 200-file
    # dataset cost 200 listings. Resolve every path from a single listing.
    rel_paths = [f"reads/{i}.bam" for i in range(25)]
    dataset = _FakeDataset([_FakeFile(rel, 10) for rel in rel_paths])
    gateway = _gateway_for(monkeypatch, dataset)

    verified = []
    size_only = gateway.validate_uploaded_files(
        "p", "d", Path("/staging"), rel_paths, lambda rel, done: verified.append((rel, done))
    )

    assert dataset.listings == 1
    assert size_only == []
    # One callback per file, carrying a running count for the progress bar.
    assert verified == [(rel, i) for i, rel in enumerate(rel_paths, start=1)]


def test_verification_falls_back_to_size_without_a_remote_checksum(monkeypatch, tmp_path):
    (tmp_path / "a.bam").write_bytes(b"12345")
    dataset = _FakeDataset([_FakeFile("a.bam", 5, checksum=False)])
    gateway = _gateway_for(monkeypatch, dataset)
    assert gateway.validate_uploaded_files("p", "d", tmp_path, ["a.bam"]) == ["a.bam"]

    dataset = _FakeDataset([_FakeFile("a.bam", 99, checksum=False)])
    gateway = _gateway_for(monkeypatch, dataset)
    with pytest.raises(ValueError, match="Size mismatch"):
        gateway.validate_uploaded_files("p", "d", tmp_path, ["a.bam"])


def test_verification_flags_a_file_missing_from_cirro(monkeypatch):
    dataset = _FakeDataset([_FakeFile("a.bam", 10)])
    gateway = _gateway_for(monkeypatch, dataset)
    with pytest.raises(ValueError, match="'b.bam' is missing from Cirro"):
        gateway.validate_uploaded_files("p", "d", Path("/staging"), ["a.bam", "b.bam"])


def test_strip_data_prefix_only_strips_a_leading_data_segment():
    assert cirro_gateway.strip_data_prefix("data/reads/a.bam") == "reads/a.bam"
    assert cirro_gateway.strip_data_prefix("reads/data/a.bam") == "reads/data/a.bam"
