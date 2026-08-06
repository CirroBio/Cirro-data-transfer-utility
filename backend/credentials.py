"""Source credentials supplied through the UI, held in memory only.

For deployments where the operator's only input channel is the browser, the
ambient-credential approach (env vars, ~/.aws) is unavailable — so credentials
are POSTed once and kept here for the life of the process.

Only AWS is here. ``gs://`` sources are read with the ambient Application
Default Credentials, or through presigned https URLs minted ahead of time by
``scripts/gcs_presign.py`` and written into the plan's ``source_location``.

Deliberate properties:

- **Never persisted.** Nothing here touches SQLite or the filesystem, so a
  restart clears everything and no secret outlives the process.
- **Write-only over HTTP.** ``status()`` returns presence and a short
  non-reversible hint (an access key id's last 4); the secrets themselves have
  no read path.
- **Never logged.** Callers must not format these values into log lines,
  exception messages, or SSE events.
- **Explicitly passed, not exported.** Values are handed to each client call
  rather than written into ``os.environ``, so they can't leak to subprocesses
  and can't race between worker threads.

Cirro's own auth is NOT here — that stays with the SDK's device-code login.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional


class CredentialError(ValueError):
    """Raised when submitted credentials are malformed."""


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aws: Optional[Dict[str, str]] = None

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

    # ---- lifecycle ------------------------------------------------------

    def clear(self, provider: str) -> None:
        if provider != "aws":
            raise CredentialError(f"Unknown provider '{provider}'")
        with self._lock:
            self._aws = None

    def status(self) -> Dict[str, Dict]:
        """Non-secret summary safe to return over HTTP."""
        with self._lock:
            aws = self._aws
        return {
            "aws": {
                "configured": aws is not None,
                # Last 4 of the key id only — enough to tell two keys apart.
                "hint": f"…{aws['aws_access_key_id'][-4:]}" if aws else None,
                "temporary": bool(aws and "aws_session_token" in aws),
                "region": aws.get("region_name") if aws else None,
            },
        }


credentials = _Store()
