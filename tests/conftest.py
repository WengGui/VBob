from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vbob.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "data")


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
