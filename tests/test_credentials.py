import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.credentials import CredentialError, credentials

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    yield
    credentials.clear("aws")


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
