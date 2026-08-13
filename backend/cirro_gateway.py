"""Single lazy connection to Cirro.

Owns the device-code login (run in a background thread so the API stays
responsive) and wraps the SDK calls the rest of the app needs. Holds both a
high-level ``DataPortal`` (browsing projects/processes/datasets) and the
low-level ``CirroApi`` (create/upload_files/resume — the only path that can
resume an interrupted upload).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, TypeVar

from backend.config import config


_FOLDER_TAG = "folder://"

# Cirro reports a dataset's files under a `data/` prefix; plan paths don't
# carry it, so it is stripped before the two are matched up.
_DATA_PREFIX = "data/"

# Cirro's API gateway throttles per tenant, so a burst from anywhere (this app,
# the web UI, another client) can 429 any single request. The SDK has no
# backoff of its own, so retry here rather than failing a whole transfer.
_THROTTLE_STATUS = 429
_THROTTLE_BACKOFF = (1, 2, 4, 8, 16)

# An upload lands before Cirro's ingest registers the dataset's files; asking
# for them during that window reports every path as missing.
_INGEST_POLL_SECONDS = 5
_INGEST_TIMEOUT_SECONDS = 900

T = TypeVar("T")


def _retry_throttled(call: Callable[[], T]) -> T:
    """Run ``call``, retrying with backoff while Cirro's API returns 429."""
    from cirro_api_client.v1.errors import UnexpectedStatus

    for delay in _THROTTLE_BACKOFF:
        try:
            return call()
        except UnexpectedStatus as exc:
            if exc.status_code != _THROTTLE_STATUS:
                raise
            time.sleep(delay)
    return call()


class NotConnected(Exception):
    pass


def strip_data_prefix(path: str) -> str:
    """A Cirro file's path as the plan spells it, without the `data/` prefix."""
    return path[len(_DATA_PREFIX):] if path.startswith(_DATA_PREFIX) else path


def _dataset_folder(dataset) -> str:
    """The in-project folder recorded on a Cirro dataset via its folder:// tag,
    or '' if it carries none."""
    for tag in getattr(dataset, "tags", None) or []:
        value = getattr(tag, "value", tag)
        if isinstance(value, str) and value.startswith(_FOLDER_TAG):
            return value[len(_FOLDER_TAG):]
    return ""


class CirroGateway:
    def __init__(self, base_url: str = None):
        self.base_url = base_url or config.base_url
        self._lock = threading.Lock()
        self._login = None
        self._portal = None
        self._client = None
        self.auth_message: Optional[str] = None
        self.status = "disconnected"  # disconnected | pending | connected | error
        self.user: Optional[str] = None
        self.error: Optional[str] = None

    # ---- auth -----------------------------------------------------------

    def start_login(self) -> Dict:
        """Begin (or resume) authentication. If a cached token is present the
        SDK skips the device flow and we connect immediately."""
        from cirro.sdk.login import DataPortalLogin

        with self._lock:
            if self.status == "connected":
                return self.auth_status()
            self.error = None
            login = DataPortalLogin(base_url=self.base_url, enable_cache=True)
            self._login = login
            try:
                # Raises ValueError when already authenticated (no device flow).
                self.auth_message = login.auth_message_markdown
                self.status = "pending"
                threading.Thread(target=self._await, args=(login,), daemon=True).start()
            except ValueError:
                self._finalize(login.auth_info)
        return self.auth_status()

    def _await(self, login) -> None:
        try:
            login.auth_info.await_completion()
            with self._lock:
                self._finalize(login.auth_info)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            with self._lock:
                self.status = "error"
                self.error = str(exc)

    def _finalize(self, auth_info) -> None:
        from cirro.cirro_client import CirroApi
        from cirro.sdk.portal import DataPortal

        self._client = CirroApi(auth_info=auth_info, base_url=self.base_url)
        self._portal = DataPortal(client=self._client)
        try:
            self.user = auth_info.get_current_user()
        except Exception:  # noqa: BLE001
            self.user = None
        self.auth_message = None
        self.status = "connected"

    def set_base_url(self, base_url: str) -> None:
        """Point at a different Cirro tenant.

        Only while disconnected: the SDK client and its cached token are bound
        to a tenant, so switching under a live session would leave the two
        disagreeing. Log out (or restart) first.
        """
        base_url = (base_url or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("Base URL is required")
        if "://" in base_url:
            raise ValueError("Host only, without a scheme (e.g. app.cirro.bio)")
        with self._lock:
            if self.status == "connected":
                raise ValueError("Log out before changing the Cirro tenant")
            self.base_url = base_url
            self._login = None
            self.auth_message = None
            self.error = None
            self.status = "disconnected"

    def logout(self) -> None:
        """Drop this process's Cirro session. The SDK's on-disk token cache is
        left alone, so a later login can still skip the device flow."""
        with self._lock:
            self._login = None
            self._portal = None
            self._client = None
            self.user = None
            self.auth_message = None
            self.error = None
            self.status = "disconnected"

    def auth_status(self) -> Dict:
        return {
            "status": self.status,
            "user": self.user,
            "auth_message": self.auth_message,
            "base_url": self.base_url,
            "error": self.error,
        }

    # ---- accessors ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.status == "connected" and self._client is not None

    def _require_portal(self):
        if not self.connected:
            raise NotConnected("Not connected to Cirro. Log in first.")
        return self._portal

    def _require_client(self):
        if not self.connected:
            raise NotConnected("Not connected to Cirro. Log in first.")
        return self._client

    # ---- browse ---------------------------------------------------------

    def list_projects(self) -> List[Dict]:
        portal = self._require_portal()
        return [{"id": p.id, "name": p.name} for p in portal.list_projects()]

    def list_ingest_processes(self) -> List[Dict]:
        portal = self._require_portal()
        return [{"id": p.id, "name": p.name} for p in portal.list_processes(ingest=True)]

    def process_identifiers(self) -> set:
        """Names and ids of ingest processes, for CSV data-type validation."""
        out = set()
        for p in self.list_ingest_processes():
            out.add(p["id"])
            out.add(p["name"])
        return out

    def resolve_project_id(self, name_or_id: str) -> str:
        for p in self.list_projects():
            if name_or_id in (p["id"], p["name"]):
                return p["id"]
        raise ValueError(f"Project not found: '{name_or_id}'")

    def resolve_process_id(self, name_or_id: str) -> str:
        for p in self.list_ingest_processes():
            if name_or_id in (p["id"], p["name"]):
                return p["id"]
        raise ValueError(f"Ingest process (data type) not found: '{name_or_id}'")

    def find_dataset(self, project_id: str, name: str, folder: str = ""):
        """Return the (most recent) DataPortalDataset with ``name`` in the
        project, or None.

        A dataset name can recur across folders within one project, so when a
        folder is given, only datasets carrying the matching ``folder://`` tag
        are considered (datasets at the project root carry no folder tag)."""
        portal = self._require_portal()
        project = portal.get_project_by_id(project_id)
        matches = [d for d in project.list_datasets() if d.name == name]
        if folder or any(_dataset_folder(d) for d in matches):
            matches = [d for d in matches if _dataset_folder(d) == folder]
        if not matches:
            return None
        # Prefer a completed dataset; otherwise the last one listed.
        completed = [d for d in matches if str(d.status).upper().endswith("COMPLETED")]
        return (completed or matches)[-1]

    def list_dataset_files(self, dataset) -> List[Dict]:
        return [
            {"relative_path": f.relative_path, "size_bytes": f.size_bytes}
            for f in dataset.list_files()
        ]

    # ---- low-level transfer ops ----------------------------------------

    def check_dataset_files(self, process_id: str, files: List[str], directory: str) -> None:
        """Validate filenames against the ingest process's naming rules.
        Raises ValueError with a helpful message on violation."""
        self._require_client().processes.check_dataset_files(
            process_id=process_id, files=files, directory=directory
        )

    def create_dataset(
        self,
        project_id: str,
        name: str,
        description: str,
        process_id: str,
        files: List[str],
        tags: List[str],
    ) -> str:
        from cirro_api_client.v1.models import Tag, UploadDatasetRequest

        request = UploadDatasetRequest(
            process_id=process_id,
            name=name,
            description=description or "",
            expected_files=files,
            tags=[Tag(value=t) for t in tags],
        )
        resp = _retry_throttled(lambda: self._require_client().datasets.create(
            project_id=project_id, upload_request=request
        ))
        return resp.id

    def upload_files(
        self,
        project_id: str,
        dataset_id: str,
        directory: str,
        files: List[str],
        resume: bool = False,
    ) -> None:
        _retry_throttled(lambda: self._require_client().datasets.upload_files(
            project_id=project_id,
            dataset_id=dataset_id,
            directory=directory,
            files=files,
            resume=resume,
        ))

    def dataset_status(self, project_id: str, dataset_id: str) -> str:
        detail = _retry_throttled(
            lambda: self._require_client().datasets.get(project_id, dataset_id)
        )
        status = getattr(detail, "status", "")
        # Normalize an enum (Status.PENDING) or string to its bare value.
        return str(getattr(status, "value", None) or status).upper()

    def wait_for_ingest(self, project_id: str, dataset_id: str) -> str:
        """Block until Cirro finishes registering an uploaded dataset's files.

        Returns the settled status. Raises if ingest fails or does not settle
        within _INGEST_TIMEOUT_SECONDS."""
        deadline = time.monotonic() + _INGEST_TIMEOUT_SECONDS
        while True:
            status = self.dataset_status(project_id, dataset_id)
            if status == "FAILED":
                raise ValueError(f"Cirro ingest failed for dataset {dataset_id}")
            if status != "PENDING":
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Cirro dataset {dataset_id} still PENDING after "
                    f"{_INGEST_TIMEOUT_SECONDS}s of ingest"
                )
            time.sleep(_INGEST_POLL_SECONDS)

    def checksum_method(self) -> str:
        return self._require_client().configuration.checksum_method_display

    def validate_uploaded_files(
        self,
        project_id: str,
        dataset_id: str,
        directory: Path,
        rel_paths: List[str],
        on_verified: Optional[Callable[[str, int], None]] = None,
    ) -> List[str]:
        """Confirm every finalized Cirro file matches the local staged file by
        checksum. Returns the list of files that could only be size-verified
        (remote checksum unavailable). Raises ValueError on a real mismatch.

        ``on_verified`` is called with (relative_path, files_done) after each
        file: this phase costs a remote stat plus a full local re-hash per file,
        so without progress it reads as a hang on a large dataset.
        """
        portal = self._require_portal()
        project = portal.get_project_by_id(project_id)
        dataset = project.get_dataset_by_id(dataset_id)
        # List the dataset once. The SDK's dataset.get_file() re-fetches the
        # whole manifest on every call, so resolving paths one at a time costs a
        # full listing per file.
        remote = {
            strip_data_prefix(f.relative_path): f
            for f in _retry_throttled(dataset.list_files)
        }
        size_only: List[str] = []
        for done, rel in enumerate(rel_paths, start=1):
            cirro_file = remote.get(rel)
            if cirro_file is None:
                raise ValueError(f"'{rel}' is missing from Cirro after upload")
            local = directory / rel
            try:
                _retry_throttled(lambda f=cirro_file: f.validate(str(local)))
            except RuntimeWarning:
                # Remote checksum unavailable — fall back to a size comparison.
                if cirro_file.size_bytes != local.stat().st_size:
                    raise ValueError(f"Size mismatch after upload for '{rel}'")
                size_only.append(rel)
            if on_verified:
                on_verified(rel, done)
        return size_only


gateway = CirroGateway()
