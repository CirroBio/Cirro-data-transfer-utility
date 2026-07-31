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

import threading
import time
from typing import Dict, Optional

# `gcloud auth print-access-token` mints a ~1 hour token. The exact lifetime is
# not in the token, so this is only used to tell the operator how stale theirs is.
GCP_TOKEN_NOMINAL_LIFETIME_SECONDS = 3600


class CredentialError(ValueError):
    """Raised when submitted credentials are malformed."""


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aws: Optional[Dict[str, str]] = None
        self._gcp_token: Optional[str] = None
        self._gcp_token_set_at: Optional[float] = None

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

    def set_gcp_access_token(self, access_token: str) -> None:
        """Accept an OAuth access token, as printed by
        ``gcloud auth print-access-token``.

        Deliberately not a service account key: a bearer token needs no key file
        on the server, and it expires on its own, so a paste that is forgotten
        about stops working within the hour.
        """
        token = (access_token or "").strip()
        if not token:
            raise CredentialError("Access token is required")
        if any(c.isspace() for c in token):
            raise CredentialError(
                "Access token contains whitespace — paste only the token, with "
                "no surrounding output"
            )
        with self._lock:
            self._gcp_token = token
            self._gcp_token_set_at = time.time()

    def gcp_credentials(self):
        """A google-auth credentials object, or None to use the ambient ADC.

        The token cannot be refreshed — there is no refresh token or key behind
        it — so once it expires the operator has to paste a new one.
        """
        with self._lock:
            token = self._gcp_token
        if token is None:
            return None
        from google.oauth2.credentials import Credentials

        return Credentials(token=token)

    # ---- lifecycle ------------------------------------------------------

    def clear(self, provider: str) -> None:
        with self._lock:
            if provider == "aws":
                self._aws = None
            elif provider == "gcp":
                self._gcp_token = None
                self._gcp_token_set_at = None
            else:
                raise CredentialError(f"Unknown provider '{provider}'")

    def status(self) -> Dict[str, Dict]:
        """Non-secret summary safe to return over HTTP.

        Nothing derived from the GCP token is reported — not even a prefix, since
        a bearer token is usable in whole or in part by an attacker who has the
        rest. Its age stands in for identity.
        """
        with self._lock:
            aws = self._aws
            token_set_at = self._gcp_token_set_at
        return {
            "aws": {
                "configured": aws is not None,
                # Last 4 of the key id only — enough to tell two keys apart.
                "hint": f"…{aws['aws_access_key_id'][-4:]}" if aws else None,
                "temporary": bool(aws and "aws_session_token" in aws),
                "region": aws.get("region_name") if aws else None,
            },
            "gcp": {
                "configured": token_set_at is not None,
                "age_seconds": (
                    int(time.time() - token_set_at) if token_set_at is not None else None
                ),
                "nominal_lifetime_seconds": GCP_TOKEN_NOMINAL_LIFETIME_SECONDS,
            },
        }


credentials = _Store()
