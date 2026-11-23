from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import get_connection
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "clan.db",
        upload_dir=tmp_path / "uploads" / "screenshots",
        session_ttl_hours=24,
        admin_username=None,
        admin_password=None,
        cookie_secure=False,
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_conn(test_settings: Settings, app: FastAPI) -> Iterator[sqlite3.Connection]:
    _ = app
    with get_connection(test_settings.db_path) as conn:
        yield conn


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    resp = client.post(
        "/api/auth/setup",
        json={
            "username": "lider",
            "password": "StrongPassword123!",
            "clanName": "Test Klanı",
        },
    )
    assert resp.status_code == 201, resp.text
    return client
