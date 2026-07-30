"""
Single source of truth for the research database connection.

ALL modules MUST use ``get_conn()`` instead of constructing their own
``sqlite3.connect(path)`` with ``__file__``-relative path resolution.

Why this exists (Phase 1.6 incident):
    ``commodity_engine/snapshot.py`` defined its own ``DB_PATH`` via
    ``os.path.join(os.path.dirname(__file__), "..", "database", ...)`` but
    the connection helper referenced a differently-named variable. The
    NameError was swallowed by a bare ``except`` and surfaced only as
    "macro section empty" at runtime — a classic multi-module reliability
    trap. Centralizing the path here removes the whole class of bugs.

Usage:
    from db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    ...
"""

import os
import sqlite3

_DB_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "database",
        "vibe_research.db",
    )
)


def db_path() -> str:
    """Absolute path to the research SQLite database."""
    return _DB_PATH


def exists() -> bool:
    """Whether the research DB file is present."""
    return os.path.exists(_DB_PATH)


def get_conn() -> sqlite3.Connection:
    """Return a connection to the research DB.

    Raises FileNotFoundError if the DB is missing (fail loud, not silent).
    """
    if not exists():
        raise FileNotFoundError(f"research DB not found: {_DB_PATH}")
    return sqlite3.connect(_DB_PATH)
