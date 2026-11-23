from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.config import Settings


def create_connection(db_path: Path | str) -> sqlite3.Connection:
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        path_str,
        timeout=5.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    # busy_timeout MUST precede journal_mode=WAL to avoid transient lock errors
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def get_connection(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = create_connection(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    with get_connection(settings.db_path) as conn:
        yield conn
