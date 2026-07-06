from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.migrations import current_schema_version
from core.portable_export import server_hash_status
from core.version import __version__


def _display_path(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return f".../{path.name}"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".write-test-", dir=path)
        os.close(handle)
        Path(name).unlink()
        return True
    except OSError:
        return False


def _latest_backup(backup_dir: Path) -> str | None:
    candidates = [path for path in backup_dir.glob("*.zip") if path.is_file()]
    if not candidates:
        return None
    modified = max(path.stat().st_mtime for path in candidates)
    return datetime.fromtimestamp(modified, timezone.utc).isoformat().replace("+00:00", "Z")


def build_report(
    conn: sqlite3.Connection,
    *,
    base_dir: Path,
    database_path: Path,
    data_dir: Path,
    media_dir: Path,
    server_executable: Path,
    log_path: Path,
) -> dict:
    counts = {}
    for key, table in (
        ("projects", "projects"),
        ("media", "media"),
        ("hotspots", "hotspots"),
        ("gpx_tracks", "gpx_tracks"),
        ("mbtiles_sources", "map_sources"),
    ):
        counts[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    hash_status = server_hash_status(server_executable)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "panorama_studio_version": __version__,
        "schema_version": current_schema_version(conn),
        "python_version": platform.python_version(),
        "operating_system": platform.platform(),
        "paths": {
            "database": _display_path(database_path, base_dir),
            "media": _display_path(media_dir, base_dir),
            "log": _display_path(log_path, base_dir),
        },
        "free_disk_bytes": shutil.disk_usage(data_dir).free,
        "counts": counts,
        "writable": {
            "data": _writable(data_dir),
            "media": _writable(media_dir),
        },
        "portable_server": hash_status,
        "last_backup_at": _latest_backup(data_dir / "backups"),
    }
