from __future__ import annotations

import sqlite3

VERSION = 1
NAME = "initial"


def _column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            thumb_path TEXT,
            title TEXT NOT NULL,
            project TEXT DEFAULT 'Default',
            category TEXT DEFAULT '',
            description TEXT DEFAULT '',
            favorite INTEGER DEFAULT 0,
            visible INTEGER DEFAULT 1,
            start_yaw REAL NULL,
            start_pitch REAL NULL,
            start_fov REAL NULL,
            created_at REAL,
            updated_at REAL
        )
        """
    )
    for name, ddl in (
        ("category", "TEXT DEFAULT ''"),
        ("start_yaw", "REAL NULL"),
        ("start_pitch", "REAL NULL"),
        ("start_fov", "REAL NULL"),
    ):
        _column(conn, "media", name, ddl)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            cover_media_id INTEGER NULL,
            start_media_id INTEGER NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (cover_media_id) REFERENCES media(id) ON DELETE SET NULL,
            FOREIGN KEY (start_media_id) REFERENCES media(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_media (
            project_id INTEGER NOT NULL,
            media_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, media_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_project_media_project_sort "
        "ON project_media(project_id, sort_order)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotspots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_media_id INTEGER NOT NULL,
            action_type TEXT NOT NULL CHECK (action_type IN ('panorama', 'info')),
            yaw REAL NOT NULL,
            pitch REAL NOT NULL,
            title TEXT DEFAULT '',
            info_text TEXT DEFAULT '',
            target_media_id INTEGER,
            visible INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (source_media_id) REFERENCES media(id) ON DELETE CASCADE,
            FOREIGN KEY (target_media_id) REFERENCES media(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hotspots_source_media_id "
        "ON hotspots(source_media_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hotspots_target_media_id "
        "ON hotspots(target_media_id)"
    )
