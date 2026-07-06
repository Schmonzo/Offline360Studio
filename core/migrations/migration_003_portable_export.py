from __future__ import annotations

import sqlite3

VERSION = 3
NAME = "portable_export"


def upgrade(conn: sqlite3.Connection) -> None:
    """Schema marker for installations that include the hardened portable export."""
    conn.execute("SELECT 1")
