from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import app as panorama_app
from core import backup, portable_export
from core.migrations import LATEST_SCHEMA_VERSION, migrate
from core.version import __version__

ROOT = Path(__file__).resolve().parents[1]


class VersionAndMigrationTests(unittest.TestCase):
    def test_central_version_is_used(self) -> None:
        self.assertEqual(panorama_app.app.config["VERSION"], __version__)
        self.assertEqual(backup.APP_VERSION, __version__)
        self.assertEqual(portable_export.EXPORT_VERSION, __version__)

    def test_no_concrete_version_is_duplicated_in_source_or_docs(self) -> None:
        forbidden = ("0." + "3.1", "0." + "8.0", "0." + "9.0")
        excluded_directories = {
            ".git",
            ".venv",
            "build",
            "__pycache__",
            "data",
            "media",
        }
        offenders = []
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() not in {".html", ".js", ".py", ".md"}
                or excluded_directories.intersection(path.parts)
                or path == ROOT / "core" / "version.py"
            ):
                continue
            content = path.read_text(encoding="utf-8")
            if __version__ in content or any(value in content for value in forbidden):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_migrations_run_once_and_build_empty_database(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            self.assertEqual(migrate(conn), LATEST_SCHEMA_VERSION)
            self.assertEqual(migrate(conn), LATEST_SCHEMA_VERSION)
            rows = conn.execute(
                "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version"
            ).fetchall()
            self.assertEqual(rows, [(1, 1), (2, 1), (3, 1)])
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue({"media", "projects", "map_sources"} <= tables)

    def test_existing_database_is_migrated_without_data_loss(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.execute(
                "CREATE TABLE media (id INTEGER PRIMARY KEY, type TEXT NOT NULL, "
                "file_path TEXT NOT NULL UNIQUE, thumb_path TEXT, title TEXT NOT NULL, "
                "project TEXT, description TEXT, favorite INTEGER, visible INTEGER, "
                "created_at REAL, updated_at REAL)"
            )
            conn.execute(
                "INSERT INTO media(id, type, file_path, title) "
                "VALUES (7, 'photo', 'media/photos/old.jpg', 'Altbestand')"
            )
            migrate(conn)
            row = conn.execute(
                "SELECT id, title, gps_source FROM media WHERE id=7"
            ).fetchone()
            self.assertEqual(row, (7, "Altbestand", None))


class DiagnosticsAndRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        data = root / "data"
        media = root / "media"
        server = root / "server.exe"
        server.write_bytes(b"portable server")
        digest = hashlib.sha256(server.read_bytes()).hexdigest()
        server.with_name("server.exe.sha256").write_text(
            f"{digest}  server.exe\n", encoding="ascii"
        )
        self.patch = patch.multiple(
            panorama_app,
            DATA_DIR=data,
            CONFIG_DIR=data / "config",
            MEDIA_DIR=media,
            PHOTO_DIR=media / "photos",
            VIDEO_DIR=media / "videos",
            THUMB_DIR=media / "thumbs",
            DB_PATH=data / "OFFLINE360_STUDIO.db",
            MAPS_DIR=data / "maps",
            PORTABLE_SERVER_EXE=server,
            LOG_PATH=root / "logs" / "offline360-studio.log",
        )
        self.patch.start()
        panorama_app.init_db()
        panorama_app.app.config["TESTING"] = True

    def tearDown(self) -> None:
        self.patch.stop()
        self.temporary.cleanup()

    def test_diagnostics_endpoint_and_server_hash(self) -> None:
        client = panorama_app.app.test_client()
        version_response = client.get("/api/version")
        self.assertEqual(version_response.status_code, 200)
        self.assertEqual(version_response.get_json(), {"version": __version__})
        self.assertEqual(version_response.headers["Cache-Control"], "no-store")

        response = client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertEqual(report["OFFLINE360_STUDIO_version"], __version__)
        self.assertEqual(
            report["OFFLINE360_STUDIO_version"],
            version_response.get_json()["version"],
        )
        self.assertEqual(report["schema_version"], LATEST_SCHEMA_VERSION)
        self.assertTrue(report["portable_server"]["sha256_valid"])
        self.assertNotIn(self.temporary.name, json.dumps(report))

    def test_portable_server_hash_mismatch_is_reported(self) -> None:
        panorama_app.PORTABLE_SERVER_EXE.write_bytes(b"manipulated")
        status = portable_export.server_hash_status(
            panorama_app.PORTABLE_SERVER_EXE
        )
        self.assertTrue(status["present"])
        self.assertFalse(status["sha256_valid"])
        self.assertEqual(status["status"], "portable_server_hash_mismatch")

    def test_logging_rotation_is_configured(self) -> None:
        handler = panorama_app.configure_logging(panorama_app.LOG_PATH)
        try:
            self.assertIsInstance(handler, RotatingFileHandler)
            self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 5)
        finally:
            panorama_app.app.logger.removeHandler(handler)
            logging_core = __import__("logging").getLogger("core")
            logging_core.removeHandler(handler)
            handler.close()


class BackupHardeningTests(unittest.TestCase):
    def test_manifest_checksums_and_newer_schema_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            media = root / "media"
            config = data / "config"
            maps = data / "maps"
            for directory in (config, media, maps):
                directory.mkdir(parents=True)
            database = data / "OFFLINE360_STUDIO.db"
            conn = sqlite3.connect(database)
            try:
                migrate(conn)
            finally:
                conn.close()
            artifact = backup.create_backup(
                database, config, media, False, root / "out", maps_dir=maps
            )
            with zipfile.ZipFile(artifact.path) as source:
                manifest = json.loads(source.read("manifest.json"))
                self.assertEqual(manifest["schema_version"], LATEST_SCHEMA_VERSION)
                self.assertTrue(manifest["files"])
                output = io.BytesIO()
                manifest["schema_version"] = LATEST_SCHEMA_VERSION + 1
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                    for info in source.infolist():
                        content = source.read(info)
                        if info.filename == "manifest.json":
                            content = json.dumps(manifest).encode()
                        target.writestr(info, content)
            archive = root / "newer.zip"
            archive.write_bytes(output.getvalue())
            with self.assertRaises(backup.BackupError) as caught:
                backup.validate_and_extract(archive, root / "extract")
            self.assertEqual(caught.exception.code, "schema_version_too_new")


class ReleaseAndSmokeContractTests(unittest.TestCase):
    def test_release_requires_clean_worktree(self) -> None:
        script = (ROOT / "tools" / "release" / "build-release.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("git status --porcelain", script)
        self.assertIn("Git-Arbeitsbaum ist nicht sauber", script)

    def test_release_test_steps_are_labeled(self) -> None:
        script = (ROOT / "tools" / "release" / "build-release.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('Invoke-NamedStep "Python tests..." "Python tests OK"', script)
        self.assertIn(
            'Invoke-NamedStep "JavaScript checks..." "JavaScript checks OK"',
            script,
        )
        self.assertIn('Invoke-NamedStep "Go tests..." "Go tests OK"', script)

    def test_smoke_test_uses_temporary_runtime_root(self) -> None:
        source = (ROOT / "tools" / "smoke_test.py").read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory", source)
        self.assertIn("OFFLINE360_STUDIO_RUNTIME_ROOT", source)
        self.assertIn("/api/diagnostics", source)


if __name__ == "__main__":
    unittest.main()

