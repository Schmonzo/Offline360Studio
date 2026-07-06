from __future__ import annotations

import sqlite3

from core import mbtiles

VERSION = 2
NAME = "gps_and_maps"


def _column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def upgrade(conn: sqlite3.Connection) -> None:
    for name, ddl in (
        ("captured_at", "REAL NULL"),
        ("latitude", "REAL NULL"),
        ("longitude", "REAL NULL"),
        ("altitude", "REAL NULL"),
        ("gps_source", "TEXT NULL"),
        ("gps_updated_at", "REAL NULL"),
    ):
        _column(conn, "media", name, ddl)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpx_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            project_id INTEGER NULL,
            original_filename TEXT NOT NULL,
            imported_at REAL NOT NULL,
            point_count INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpx_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            elevation REAL NULL,
            recorded_at REAL NULL,
            FOREIGN KEY (track_id) REFERENCES gpx_tracks(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_gpx_points_track_sequence "
        "ON gpx_points(track_id, sequence)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS map_sources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            filename TEXT NOT NULL UNIQUE,
            format TEXT NOT NULL,
            map_type TEXT NOT NULL DEFAULT 'raster'
                CHECK (map_type IN ('raster', 'vector')),
            schema_type TEXT NOT NULL DEFAULT 'flat'
                CHECK (schema_type IN ('flat', 'normalized')),
            min_zoom INTEGER NULL,
            max_zoom INTEGER NULL,
            bounds TEXT NULL,
            center TEXT NULL,
            vector_layers TEXT NOT NULL DEFAULT '[]',
            attribution TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 0,
            imported_at REAL NOT NULL
        )
        """
    )
    for name, ddl in (
        ("schema_type", "TEXT NOT NULL DEFAULT 'flat' CHECK (schema_type IN ('flat', 'normalized'))"),
        ("map_type", "TEXT NOT NULL DEFAULT 'raster' CHECK (map_type IN ('raster', 'vector'))"),
        ("center", "TEXT NULL"),
        ("vector_layers", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        _column(conn, "map_sources", name, ddl)
    raster = ", ".join(f"'{item}'" for item in sorted(mbtiles.RASTER_FORMATS))
    vector = ", ".join(f"'{item}'" for item in sorted(mbtiles.VECTOR_FORMATS))
    conn.execute(
        f"""
        UPDATE map_sources SET map_type = CASE
            WHEN lower(format) IN ({raster}) THEN 'raster'
            WHEN lower(format) IN ({vector}) THEN 'vector'
            ELSE map_type END
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_map_sources_single_active "
        "ON map_sources(active) WHERE active = 1"
    )
    for operation, clause in (
        ("insert", "INSERT"),
        ("update", "UPDATE OF latitude, longitude, altitude, gps_source"),
    ):
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS validate_media_gps_{operation}
            BEFORE {clause} ON media
            BEGIN
                SELECT CASE WHEN NEW.latitude IS NOT NULL AND (
                    typeof(NEW.latitude) NOT IN ('real', 'integer')
                    OR NEW.latitude < -90 OR NEW.latitude > 90
                ) THEN RAISE(ABORT, 'invalid latitude') END;
                SELECT CASE WHEN NEW.longitude IS NOT NULL AND (
                    typeof(NEW.longitude) NOT IN ('real', 'integer')
                    OR NEW.longitude < -180 OR NEW.longitude > 180
                ) THEN RAISE(ABORT, 'invalid longitude') END;
                SELECT CASE WHEN NEW.altitude IS NOT NULL AND (
                    typeof(NEW.altitude) NOT IN ('real', 'integer')
                    OR NEW.altitude < -1.7976931348623157e308
                    OR NEW.altitude > 1.7976931348623157e308
                ) THEN RAISE(ABORT, 'invalid altitude') END;
                SELECT CASE WHEN NEW.gps_source IS NOT NULL
                    AND NEW.gps_source NOT IN ('exif', 'gpx', 'manual')
                THEN RAISE(ABORT, 'invalid gps_source') END;
            END
            """
        )
