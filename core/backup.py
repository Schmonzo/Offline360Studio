from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO


APP_NAME = "Panorama Studio"
APP_VERSION = "0.3.1"
BACKUP_VERSION = 1
MAX_BACKUP_SIZE = 10 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100_000
MAX_MANIFEST_SIZE = 64 * 1024
DATABASE_FILENAME = "panorama_studio.db"
CONFIG_EXTENSIONS = {".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml"}
MEDIA_EXTENSIONS = {
    "photos": {".jpg", ".jpeg", ".png"},
    "videos": {".mp4", ".m4v", ".mov"},
    "thumbs": {".jpg", ".jpeg", ".png"},
}
REQUIRED_TABLES = {"media", "projects", "project_media", "hotspots"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

README_TEXT = """Panorama Studio backup

This ZIP archive contains a consistent SQLite database backup and local
configuration files. Media files are included only when manifest.json sets
"includes_media" to true.

Restore this archive only through Panorama Studio's Backup & Restore section.
Do not edit the archive or extract it over an installation manually.
The maximum accepted ZIP size and extracted size are each 10 GB.
"""


class BackupError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class BackupArtifact:
    path: Path
    filename: str
    manifest: dict


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _regular_files(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def _config_files(config_dir: Path):
    for path in _regular_files(config_dir):
        if path.suffix.lower() in CONFIG_EXTENSIONS:
            yield path


def _media_files(media_dir: Path):
    for path in _regular_files(media_dir):
        relative = path.relative_to(media_dir)
        if (
            len(relative.parts) >= 2
            and relative.parts[0] in MEDIA_EXTENSIONS
            and path.suffix.lower() in MEDIA_EXTENSIONS[relative.parts[0]]
        ):
            yield path


def _copy_database(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BackupError("database_missing", "Die lokale Datenbank wurde nicht gefunden.", 500)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(source)) as source_conn, closing(
            sqlite3.connect(destination)
        ) as target_conn:
            source_conn.backup(target_conn)
    except sqlite3.Error as exc:
        raise BackupError(
            "database_backup_failed",
            "Die Datenbank konnte nicht konsistent gesichert werden.",
            500,
        ) from exc


def _database_counts(database_path: Path) -> tuple[int, int]:
    try:
        with closing(sqlite3.connect(database_path)) as conn:
            media_count = int(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0])
            project_count = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        return media_count, project_count
    except sqlite3.Error as exc:
        raise BackupError("database_invalid", "Die Datenbank konnte nicht gelesen werden.", 500) from exc


def create_backup(
    database_path: Path,
    config_dir: Path,
    media_dir: Path,
    includes_media: bool,
    output_dir: Path,
    *,
    filename_prefix: str = "panorama-studio-backup",
) -> BackupArtifact:
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="panorama-backup-", dir=output_dir))
    try:
        database_copy = workspace / DATABASE_FILENAME
        _copy_database(database_path, database_copy)
        media_count, project_count = _database_counts(database_copy)
        media_files = list(_media_files(media_dir)) if includes_media else []
        manifest = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "backup_version": BACKUP_VERSION,
            "created_at": utc_timestamp(),
            "includes_media": includes_media,
            "database_filename": DATABASE_FILENAME,
            "media_count": media_count,
            "project_count": project_count,
        }
        filename = f"{filename_prefix}-{safe_timestamp()}.zip"
        archive_path = output_dir / filename
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            archive.writestr("README.txt", README_TEXT)
            archive.write(database_copy, DATABASE_FILENAME)
            for path in _config_files(config_dir):
                archive.write(path, f"config/{path.relative_to(config_dir).as_posix()}")
            for path in media_files:
                archive.write(path, f"media/{path.relative_to(media_dir).as_posix()}")
        return BackupArtifact(archive_path, filename, manifest)
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(
            "backup_export_failed", "Das Backup konnte nicht erstellt werden.", 500
        ) from exc
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def save_upload(stream: BinaryIO, destination: Path, max_size: int = MAX_BACKUP_SIZE) -> int:
    written = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_size:
                    raise BackupError(
                        "backup_too_large",
                        f"Das Backup überschreitet das Limit von {max_size // (1024**3)} GB.",
                        413,
                    )
                target.write(chunk)
    except BackupError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise BackupError("upload_failed", "Die ZIP-Datei konnte nicht gespeichert werden.", 500) from exc
    return written


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise BackupError("unsafe_archive_path", "Das Backup enthält einen unsicheren Pfad.")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise BackupError("unsafe_archive_path", "Absolute Pfade sind im Backup nicht erlaubt.")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError("unsafe_archive_path", "Das Backup enthält einen unsicheren Pfad.")
    for part in path.parts:
        device_name = part.split(".", 1)[0].upper()
        if (
            part.endswith((" ", "."))
            or any(character in part for character in '<>:"|?*')
            or device_name in WINDOWS_RESERVED_NAMES
        ):
            raise BackupError("unsafe_archive_path", "Das Backup enthält einen ungültigen Dateinamen.")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def _validate_expected_path(path: PurePosixPath, manifest: dict, is_dir: bool) -> None:
    name = path.as_posix()
    if is_dir:
        if path.parts[0] == "config":
            return
        if path.parts[0] == "media" and (
            len(path.parts) == 1 or path.parts[1] in MEDIA_EXTENSIONS
        ):
            return
        raise BackupError("unexpected_archive_path", f"Unerwarteter Verzeichnispfad: {name}")
    if name in {"manifest.json", "README.txt", manifest["database_filename"]}:
        return
    if path.parts[0] == "config" and len(path.parts) >= 2:
        if path.suffix.lower() not in CONFIG_EXTENSIONS:
            raise BackupError("invalid_file_type", f"Unzulässige Konfigurationsdatei: {name}")
        return
    if path.parts[0] == "media" and len(path.parts) >= 3:
        media_kind = path.parts[1]
        if not manifest["includes_media"]:
            raise BackupError("unexpected_media", "Das Manifest deklariert keine Mediendateien.")
        if media_kind not in MEDIA_EXTENSIONS or path.suffix.lower() not in MEDIA_EXTENSIONS[media_kind]:
            raise BackupError("invalid_file_type", f"Unzulässige Mediendatei: {name}")
        return
    raise BackupError("unexpected_archive_path", f"Unerwarteter Pfad im Backup: {name}")


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        info = archive.getinfo("manifest.json")
    except KeyError as exc:
        raise BackupError("manifest_missing", "manifest.json fehlt im Backup.") from exc
    if info.file_size > MAX_MANIFEST_SIZE:
        raise BackupError("manifest_invalid", "manifest.json ist zu groß.")
    try:
        manifest = json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise BackupError("manifest_invalid", "manifest.json ist ungültig.") from exc
    required = {
        "app_name": str,
        "app_version": str,
        "backup_version": int,
        "created_at": str,
        "includes_media": bool,
        "database_filename": str,
        "media_count": int,
        "project_count": int,
    }
    if not isinstance(manifest, dict) or any(
        key not in manifest or type(manifest[key]) is not expected
        for key, expected in required.items()
    ):
        raise BackupError("manifest_invalid", "manifest.json enthält nicht alle erwarteten Felder.")
    if manifest["app_name"] != APP_NAME:
        raise BackupError("manifest_invalid", "Das Backup gehört nicht zu Panorama Studio.")
    if manifest["backup_version"] != BACKUP_VERSION:
        raise BackupError(
            "backup_version_unsupported",
            f"Backup-Version {manifest['backup_version']} wird nicht unterstützt.",
        )
    database_name = manifest["database_filename"]
    if (
        database_name != Path(database_name).name
        or PurePosixPath(database_name).suffix.lower() not in {".db", ".sqlite", ".sqlite3"}
    ):
        raise BackupError("manifest_invalid", "Der Datenbank-Dateiname im Manifest ist ungültig.")
    if manifest["media_count"] < 0 or manifest["project_count"] < 0:
        raise BackupError("manifest_invalid", "Die Zähler im Manifest sind ungültig.")
    return manifest


def validate_and_extract(archive_path: Path, destination: Path) -> dict:
    try:
        with zipfile.ZipFile(archive_path, "r", allowZip64=True) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise BackupError("archive_too_many_files", "Das Backup enthält zu viele Dateien.")
            manifest = _read_manifest(archive)
            names: set[str] = set()
            names_casefold: set[str] = set()
            total_size = 0
            for info in infos:
                path = _safe_member_path(info.filename.rstrip("/"))
                canonical_name = path.as_posix()
                canonical_casefold = canonical_name.casefold()
                if canonical_name in names or canonical_casefold in names_casefold:
                    raise BackupError("duplicate_archive_path", "Das Backup enthält doppelte Pfade.")
                names.add(canonical_name)
                names_casefold.add(canonical_casefold)
                if info.flag_bits & 0x1:
                    raise BackupError("encrypted_archive", "Verschlüsselte ZIP-Einträge werden nicht unterstützt.")
                if _is_symlink(info):
                    raise BackupError("symlink_not_allowed", "Symlinks sind im Backup nicht erlaubt.")
                mode_type = stat.S_IFMT(info.external_attr >> 16)
                if mode_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise BackupError("invalid_file_type", "Das Backup enthält einen speziellen Dateityp.")
                _validate_expected_path(path, manifest, info.is_dir())
                total_size += info.file_size
                if total_size > MAX_BACKUP_SIZE:
                    raise BackupError("backup_too_large", "Der entpackte Inhalt überschreitet das Größenlimit.", 413)
            required_names = {"manifest.json", "README.txt", manifest["database_filename"]}
            if not required_names.issubset(names):
                raise BackupError("backup_incomplete", "Das Backup enthält nicht alle Pflichtdateien.")
            if archive.testzip() is not None:
                raise BackupError("archive_corrupt", "Die ZIP-Datei ist beschädigt.")
            destination.mkdir(parents=True, exist_ok=True)
            for info in infos:
                path = _safe_member_path(info.filename.rstrip("/"))
                target = destination.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            return manifest
    except BackupError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError) as exc:
        raise BackupError("archive_corrupt", "Die Datei ist kein gültiges ZIP-Backup.") from exc


def check_database(database_path: Path) -> None:
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
        ) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError("database_integrity_failed", "Die Backup-Datenbank ist beschädigt.")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not REQUIRED_TABLES.issubset(tables):
                raise BackupError(
                    "database_schema_invalid",
                    "Die Backup-Datenbank hat nicht das erwartete Schema.",
                )
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupError(
                    "database_integrity_failed",
                    "Die Backup-Datenbank verletzt Fremdschlüsselbeziehungen.",
                )
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError("database_integrity_failed", "Die Backup-Datenbank ist ungültig.") from exc


def _prepare_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _swap_path(new_path: Path, target: Path, rollback_root: Path) -> tuple[Path, Path | None]:
    old_path = rollback_root / target.name
    if target.exists():
        os.replace(target, old_path)
    else:
        old_path = None
    try:
        os.replace(new_path, target)
    except OSError:
        if old_path is not None and old_path.exists():
            os.replace(old_path, target)
        raise
    return target, old_path


def restore_backup(
    archive_path: Path,
    database_path: Path,
    config_dir: Path,
    media_dir: Path,
    safety_backup_dir: Path,
) -> dict:
    staging_root = Path(tempfile.mkdtemp(prefix="panorama-restore-"))
    prepared: list[Path] = []
    swaps: list[tuple[Path, Path | None]] = []
    safety_artifact: BackupArtifact | None = None
    try:
        extracted = staging_root / "extracted"
        manifest = validate_and_extract(archive_path, extracted)
        incoming_database = extracted / manifest["database_filename"]
        check_database(incoming_database)
        actual_media_count, actual_project_count = _database_counts(incoming_database)
        if actual_project_count != manifest["project_count"]:
            raise BackupError(
                "manifest_mismatch",
                "Die Projektanzahl stimmt nicht mit dem Manifest überein.",
            )
        if actual_media_count != manifest["media_count"]:
            raise BackupError(
                "manifest_mismatch",
                "Die Medienanzahl stimmt nicht mit dem Manifest überein.",
            )

        safety_artifact = create_backup(
            database_path,
            config_dir,
            media_dir,
            True,
            safety_backup_dir,
            filename_prefix="pre-restore",
        )

        token = uuid.uuid4().hex
        prepared_database = database_path.parent / f".{database_path.name}.restore-{token}"
        shutil.copy2(incoming_database, prepared_database)
        prepared.append(prepared_database)

        prepared_config = config_dir.parent / f".{config_dir.name}.restore-{token}"
        _prepare_tree(extracted / "config", prepared_config)
        prepared.append(prepared_config)

        prepared_media = None
        if manifest["includes_media"]:
            prepared_media = media_dir.parent / f".{media_dir.name}.restore-{token}"
            _prepare_tree(extracted / "media", prepared_media)
            prepared.append(prepared_media)

        rollback_root = staging_root / "rollback"
        rollback_root.mkdir()
        try:
            swaps.append(_swap_path(prepared_database, database_path, rollback_root))
            swaps.append(_swap_path(prepared_config, config_dir, rollback_root))
            if prepared_media is not None:
                swaps.append(_swap_path(prepared_media, media_dir, rollback_root))
        except OSError:
            for target, old_path in reversed(swaps):
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                if old_path is not None and old_path.exists():
                    os.replace(old_path, target)
            raise

        return {
            "status": "ok",
            "restart_required": True,
            "message": "Restore erfolgreich. Bitte Panorama Studio neu starten.",
            "safety_backup": safety_artifact.filename,
            "manifest": manifest,
        }
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "restore_failed",
            "Der Restore konnte nicht atomar abgeschlossen werden; bestehende Daten wurden beibehalten.",
            500,
        ) from exc
    finally:
        for path in prepared:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        shutil.rmtree(staging_root, ignore_errors=True)
