"""Source credentials supplied through the UI, held in memory only.

For deployments where the operator's only input channel is the browser, the
ambient-credential approach (env vars, ~/.aws, gcloud ADC) is unavailable — so
credentials are POSTed once and kept here for the life of the process.

Deliberate properties:

- **Never persisted.** Nothing here touches SQLite or the filesystem, so a
  restart clears everything and no secret outlives the process.
- **Write-only over HTTP.** ``status()`` returns presence and a short
  non-reversible hint (an access key id's last 4, a service account's email);
  the secrets themselves have no read path.
- **Never logged.** Callers must not format these values into log lines,
  exception messages, or SSE events.
- **Explicitly passed, not exported.** Values are handed to each client call
  rather than written into ``os.environ``, so they can't leak to subprocesses
  and can't race between worker threads.

Cirro's own auth is NOT here — that stays with the SDK's device-code login.
"""
from __future__ import annotations

import json
import threading
from typing import Dict, Optional


class CredentialError(ValueError):
    """Raised when submitted credentials are malformed."""


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aws: Optional[Dict[str, str]] = None
        self._gcp_info: Optional[Dict] = None

    # ---- AWS ------------------------------------------------------------

    def set_aws(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        if not access_key_id or not secret_access_key:
            raise CredentialError("Access key id and secret access key are both required")
        entry = {
            "aws_access_key_id": access_key_id.strip(),
            "aws_secret_access_key": secret_access_key.strip(),
        }
        if session_token:
            entry["aws_session_token"] = session_token.strip()
        if region:
            entry["region_name"] = region.strip()
        with self._lock:
            self._aws = entry

    def aws_client_kwargs(self) -> Dict[str, str]:
        """boto3 client kwargs, or empty when the ambient chain should be used."""
        with self._lock:
            return dict(self._aws) if self._aws else {}

    # ---- GCP ------------------------------------------------------------

    def set_gcp_service_account(self, service_account_json: str) -> None:
        try:
            info = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            raise CredentialError(f"Not valid JSON: {exc.msg}") from None
        if not isinstance(info, dict):
            raise CredentialError("Expected a service account JSON object")
        missing = [f for f in ("client_email", "private_key", "token_uri") if not info.get(f)]
        if missing:
            raise CredentialError(
                f"Not a service account key — missing {', '.join(missing)}"
            )
        with self._lock:
            self._gcp_info = info

    def gcp_credentials(self):
        """A google-auth credentials object, or None to use the ambient ADC."""
        with self._lock:
            info = dict(self._gcp_info) if self._gcp_info else None
        if info is None:
            return None
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(info)

    def gcp_project(self) -> Optional[str]:
        with self._lock:
            return (self._gcp_info or {}).get("project_id")

    # ---- lifecycle ------------------------------------------------------

    def clear(self, provider: str) -> None:
        with self._lock:
            if provider == "aws":
                self._aws = None
            elif provider == "gcp":
                self._gcp_info = None
            else:
                raise CredentialError(f"Unknown provider '{provider}'")

    def status(self) -> Dict[str, Dict]:
        """Non-secret summary safe to return over HTTP."""
        with self._lock:
            aws, gcp = self._aws, self._gcp_info
        return {
            "aws": {
                "configured": aws is not None,
                # Last 4 of the key id only — enough to tell two keys apart.
                "hint": f"…{aws['aws_access_key_id'][-4:]}" if aws else None,
                "temporary": bool(aws and "aws_session_token" in aws),
                "region": aws.get("region_name") if aws else None,
            },
            "gcp": {
                "configured": gcp is not None,
                "hint": gcp.get("client_email") if gcp else None,
                "project": gcp.get("project_id") if gcp else None,
            },
        }


credentials = _Store()
