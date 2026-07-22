"""Test fixtures. Points the app's data dir at a throwaway temp dir *before*
backend.config is imported, and gives each test a fresh database.
"""
import os
import tempfile

os.environ.setdefault(
    "CIRRO_TRANSFER_HOME", tempfile.mkdtemp(prefix="cirro-transfer-test-")
)

import pytest  # noqa: E402

from backend import db  # noqa: E402
from backend.config import config  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    if config.db_path.exists():
        config.db_path.unlink()
    db.init_db()
    yield
