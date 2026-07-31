import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.credentials import CredentialError, credentials

client = TestClient(app)

GCP_TOKEN = "ya29.NOT-A-REAL-ACCESS-TOKEN"


@pytest.fixture(autouse=True)
def clean_store():
    yield
    for provider in ("aws", "gcp"):
        credentials.clear(provider)


def test_aws_credentials_become_boto3_kwargs():
    credentials.set_aws("AKIAEXAMPLE0001", "secret-value", session_token="tok", region="us-west-2")
    assert credentials.aws_client_kwargs() == {
        "aws_access_key_id": "AKIAEXAMPLE0001",
        "aws_secret_access_key": "secret-value",
        "aws_session_token": "tok",
        "region_name": "us-west-2",
    }


def test_no_aws_credentials_means_ambient_chain():
    assert credentials.aws_client_kwargs() == {}


def test_aws_requires_both_halves():
    with pytest.raises(CredentialError):
        credentials.set_aws("AKIAEXAMPLE0001", "")


def test_status_exposes_a_hint_but_never_the_secret():
    credentials.set_aws("AKIAEXAMPLE0001", "super-secret", session_token="tok")
    status = credentials.status()
    assert status["aws"] == {
        "configured": True,
        "hint": "…0001",
        "temporary": True,
        "region": None,
    }
    assert "super-secret" not in json.dumps(status)


def test_credentials_endpoint_never_returns_secrets():
    body = {
        "access_key_id": "AKIAEXAMPLE0002",
        "secret_access_key": "super-secret",
        "session_token": "super-token",
    }
    posted = client.post("/credentials/aws", json=body)
    assert posted.status_code == 200
    for response in (posted, client.get("/credentials")):
        payload = response.text
        assert "super-secret" not in payload
        assert "super-token" not in payload
        assert "…0002" in payload


def test_gcp_access_token_is_validated():
    empty = client.post("/credentials/gcp", json={"access_token": "   "})
    assert empty.status_code == 400
    assert "required" in empty.json()["detail"]

    # A pasted `gcloud auth print-access-token` line that dragged along other
    # shell output would otherwise be stored and fail opaquely on every object.
    with_output = client.post(
        "/credentials/gcp", json={"access_token": "ya29.FAKE token-leftover"}
    )
    assert with_output.status_code == 400
    assert "whitespace" in with_output.json()["detail"]


def test_gcp_status_reports_age_and_never_the_token():
    res = client.post("/credentials/gcp", json={"access_token": GCP_TOKEN})
    assert res.status_code == 200
    assert res.json()["gcp"] == {
        "configured": True,
        "age_seconds": 0,
        "nominal_lifetime_seconds": 3600,
    }
    # Not even a prefix: a bearer token is usable by anyone holding the rest.
    for response in (res, client.get("/credentials")):
        assert GCP_TOKEN not in response.text
        assert "ya29" not in response.text


def test_gcp_token_becomes_static_bearer_credentials():
    credentials.set_gcp_access_token(GCP_TOKEN)
    creds = credentials.gcp_credentials()
    assert creds.token == GCP_TOKEN
    # No refresh material behind it — expiry means re-pasting, by design.
    assert creds.refresh_token is None


def test_no_gcp_token_means_ambient_adc():
    assert credentials.gcp_credentials() is None


def test_gcp_age_is_reported_as_it_grows(monkeypatch):
    credentials.set_gcp_access_token(GCP_TOKEN)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 3700)
    gcp = credentials.status()["gcp"]
    assert gcp["age_seconds"] >= 3700
    assert gcp["age_seconds"] > gcp["nominal_lifetime_seconds"]


def test_clearing_credentials_restores_the_ambient_fallback():
    credentials.set_aws("AKIAEXAMPLE0003", "secret")
    assert client.delete("/credentials/aws").json()["aws"]["configured"] is False
    assert credentials.aws_client_kwargs() == {}


def test_unknown_provider_is_rejected():
    assert client.delete("/credentials/azure").status_code == 404


def test_base_url_requires_a_bare_host():
    bad = client.post("/auth/base-url", json={"base_url": "https://app.cirro.bio"})
    assert bad.status_code == 400
    assert "without a scheme" in bad.json()["detail"]

    ok = client.post("/auth/base-url", json={"base_url": "dev.cirro.bio/"})
    assert ok.status_code == 200
    assert ok.json()["base_url"] == "dev.cirro.bio"
