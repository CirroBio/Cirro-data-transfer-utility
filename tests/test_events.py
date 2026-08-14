import threading

from fastapi.testclient import TestClient

from backend.app import app
from backend.events import RECENT_EVENTS, Broker

client = TestClient(app)


def test_new_client_starts_from_now_without_replay():
    broker = Broker()
    broker.publish({"type": "queue", "action": "enqueued", "keys": ["p/f/d"]})
    batch = broker.since(None)
    assert batch == {"seq": 1, "events": [], "gap": False}


def test_cursor_returns_only_newer_events():
    broker = Broker()
    broker.publish({"type": "ping", "n": 1})
    cursor = broker.since(None)["seq"]
    broker.publish({"type": "ping", "n": 2})
    broker.publish({"type": "ping", "n": 3})

    batch = broker.since(cursor)
    assert [e["n"] for e in batch["events"]] == [2, 3]
    assert batch["gap"] is False
    # Polling again with the advanced cursor yields nothing new.
    assert broker.since(batch["seq"])["events"] == []


def test_cursor_older_than_the_buffer_reports_a_gap():
    broker = Broker()
    broker.publish({"type": "ping", "n": 0})
    cursor = broker.since(None)["seq"]
    for n in range(RECENT_EVENTS + 1):
        broker.publish({"type": "ping", "n": n})

    batch = broker.since(cursor)
    assert batch["gap"] is True
    assert batch["events"] == []
    # The client can resume from the reported seq.
    assert broker.since(batch["seq"])["gap"] is False


def test_concurrent_publishes_keep_sequence_and_order():
    broker = Broker()
    threads = [
        threading.Thread(target=lambda w=worker: [
            broker.publish({"type": "ping", "worker": w, "n": n}) for n in range(50)
        ])
        for worker in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert broker.seq == 200
    events = broker.since(0)["events"]
    assert len(events) == 200
    for worker in range(4):
        assert [e["n"] for e in events if e["worker"] == worker] == list(range(50))


def test_poll_endpoint_hands_back_a_cursor():
    first = client.get("/events/poll").json()
    assert first["events"] == []
    assert first["gap"] is False
    assert client.get("/events/poll", params={"since": first["seq"]}).json()["events"] == []


def test_config_reports_the_events_transport():
    assert client.get("/config").json()["events_transport"] == "auto"
