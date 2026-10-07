from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from . import migration_001_initial, migration_002_maps, migration_003_portable_export

LOGGER = logging.getLogger(__name__)
Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]
MIGRATIONS: tuple[Migration, ...] = (
    (migration_001_initial.VERSION, migration_001_initial.NAME, migration_001_initial.upgrade),
    (migration_002_maps.VERSION, migration_002_maps.NAME, migration_002_maps.upgrade),
    (
        migration_003_portable_export.VERSION,
        migration_003_portable_export.NAME,
        migration_003_portable_export.upgrade,
    ),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


class MigrationError(RuntimeError):
    pass


def current_schema_version(conn: sqlite3.Connection) -> int:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if table is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    applied = {
        int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")
    }
    unknown = applied - {version for version, _, _ in MIGRATIONS}
    if unknown:
        raise MigrationError(
            "Die Datenbank verwendet eine neuere oder unbekannte Schema-Version: "
            + ", ".join(map(str, sorted(unknown)))
        )

    for version, name, upgrade in MIGRATIONS:
        if version in applied:
            continue
        LOGGER.info("Datenbankmigration gestartet: %03d %s", version, name)
        try:
            conn.execute("BEGIN IMMEDIATE")
            upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise MigrationError(
                f"Datenbankmigration {version:03d} ({name}) ist fehlgeschlagen: {exc}"
            ) from exc
        LOGGER.info("Datenbankmigration abgeschlossen: %03d %s", version, name)
    return current_schema_version(conn)

