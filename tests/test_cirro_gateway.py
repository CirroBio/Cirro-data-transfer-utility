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
