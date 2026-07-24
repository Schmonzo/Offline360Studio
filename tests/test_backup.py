from __future__ import annotations

import io
import json
import sqlite3
import stat
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as panorama_app
from core import backup


class BackupApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        data_dir = root / "data"
        media_dir = root / "media"
        self.path_patch = patch.multiple(
            panorama_app,
            DATA_DIR=data_dir,
            CONFIG_DIR=data_dir / "config",
            MEDIA_DIR=media_dir,
            PHOTO_DIR=media_dir / "photos",
            VIDEO_DIR=media_dir / "videos",
            THUMB_DIR=media_dir / "thumbs",
            DB_PATH=data_dir / "OFFLINE360_STUDIO.db",
            MAPS_DIR=data_dir / "maps",
        )
        self.path_patch.start()
        panorama_app.app.config.update(TESTING=True)
        panorama_app.init_db()
        panorama_app.CONFIG_DIR.joinpath("studio.json").write_text(
            '{"theme":"dark"}', encoding="utf-8"
        )
        panorama_app.PHOTO_DIR.joinpath("tour").mkdir()
        panorama_app.PHOTO_DIR.joinpath("tour", "pano.jpg").write_bytes(b"photo")
        panorama_app.VIDEO_DIR.joinpath("clip.mp4").write_bytes(b"video")
        with panorama_app.db() as conn:
            conn.execute(
                """
                INSERT INTO media
                (type, file_path, title, project, created_at, updated_at)
                VALUES ('photo', 'media/photos/tour/pano.jpg', 'Original', 'Tour', 1, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO projects(id, name, description, created_at, updated_at)
                VALUES (1, 'Tour', 'Test', 1, 1)
                """
            )
            conn.commit()
        self.client = panorama_app.app.test_client()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def export_backup(self, includes_media: bool, includes_maps: bool = False) -> bytes:
        response = self.client.post(
            "/api/backup/export",
            json={
                "includes_media": includes_media,
                "includes_maps": includes_maps,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        content = response.get_data()
        response.close()
        return content

    def import_backup(self, content: bytes, filename: str = "backup.zip"):
        return self.client.post(
            "/api/backup/import",
            data={"file": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    @staticmethod
    def rewrite_archive(
        content: bytes,
        *,
        skip: set[str] | None = None,
        replacements: dict[str, bytes] | None = None,
        extras: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None,
    ) -> bytes:
        output = io.BytesIO()
        skip = skip or set()
        replacements = replacements or {}
        with zipfile.ZipFile(io.BytesIO(content), "r") as source:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    if info.filename in skip:
                        continue
                    target.writestr(info, replacements.get(info.filename, source.read(info)))
                for name, data in extras or []:
                    target.writestr(name, data)
        return output.getvalue()

    def assert_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], code)
        self.assertIsInstance(payload["error"]["message"], str)

    def test_export_without_media_contains_manifest_database_config_and_readme(self) -> None:
        content = self.export_backup(False)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("OFFLINE360_STUDIO.db", names)
            self.assertIn("README.txt", names)
            self.assertIn("config/studio.json", names)
            self.assertFalse(any(name.startswith("media/") for name in names))
            self.assertEqual(
                set(manifest),
                {
                    "app_name",
                    "app_version",
                    "backup_version",
                    "schema_version",
                    "created_at",
                    "includes_media",
                    "includes_maps",
                    "database_filename",
                    "media_count",
                    "project_count",
                    "files",
                },
            )
            self.assertEqual(manifest["app_name"], "Offline360 Studio")
            self.assertEqual(manifest["app_version"], backup.APP_VERSION)
            self.assertEqual(manifest["backup_version"], 2)
            self.assertEqual(manifest["schema_version"], 3)
            self.assertIn("OFFLINE360_STUDIO.db", manifest["files"])
            self.assertFalse(manifest["includes_media"])
            self.assertFalse(manifest["includes_maps"])
            self.assertEqual(manifest["database_filename"], "OFFLINE360_STUDIO.db")
            self.assertEqual(manifest["media_count"], 1)
            self.assertEqual(manifest["project_count"], 1)

    def test_export_with_media_contains_supported_media_and_count(self) -> None:
        content = self.export_backup(True)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("media/photos/tour/pano.jpg", names)
            self.assertIn("media/videos/clip.mp4", names)
            self.assertTrue(manifest["includes_media"])
            self.assertEqual(manifest["media_count"], 1)

    def test_backup_with_and_without_offline_maps_and_restore(self) -> None:
        filename = "0123456789abcdef0123456789abcdef.mbtiles"
        map_path = panorama_app.MAPS_DIR / filename
        with closing(sqlite3.connect(map_path)) as conn:
            conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
            conn.execute(
                """
                CREATE TABLE tiles (
                    zoom_level INTEGER, tile_column INTEGER,
                    tile_row INTEGER, tile_data BLOB
                )
                """
            )
            conn.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                [
                    ("name", "Testkarte"),
                    ("format", "pbf"),
                    ("type", "baselayer"),
                    ("json", '{"vector_layers":[{"id":"test","fields":{}}]}'),
                ],
            )
            conn.execute(
                "INSERT INTO tiles VALUES (0, 0, 0, ?)",
                (b"\x1a\x0b\x0a\x04test\x28\x80\x20\x78\x02",),
            )
            conn.commit()
        with panorama_app.db() as conn:
            conn.execute(
                """
                INSERT INTO map_sources
                (name, filename, format, map_type, min_zoom, max_zoom,
                 vector_layers, active, imported_at)
                VALUES ('Testkarte', ?, 'pbf', 'vector', 0, 0,
                        '[{"id":"test","fields":{}}]', 1, 1)
                """,
                (filename,),
            )
            conn.commit()

        without_maps = self.export_backup(False, False)
        with zipfile.ZipFile(io.BytesIO(without_maps)) as archive:
            self.assertFalse(json.loads(archive.read("manifest.json"))["includes_maps"])
            self.assertFalse(any(name.startswith("maps/") for name in archive.namelist()))

        with_maps = self.export_backup(False, True)
        with zipfile.ZipFile(io.BytesIO(with_maps)) as archive:
            self.assertTrue(json.loads(archive.read("manifest.json"))["includes_maps"])
            self.assertIn(f"maps/{filename}", archive.namelist())

        map_path.unlink()
        with panorama_app.db() as conn:
            conn.execute("DELETE FROM map_sources")
            conn.commit()
        response = self.import_backup(with_maps)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(map_path.read_bytes()[:16], b"SQLite format 3\x00")
        with panorama_app.db() as conn:
            self.assertEqual(
                tuple(
                    conn.execute(
                        "SELECT name, active, map_type FROM map_sources"
                    ).fetchone()
                ),
                ("Testkarte", 1, "vector"),
            )

    def test_export_database_contains_gps_and_gpx_data(self) -> None:
        with panorama_app.db() as conn:
            conn.execute(
                """
                UPDATE media SET latitude=46.5, longitude=7.5, altitude=1200,
                                 gps_source='manual', gps_updated_at=2
                """
            )
            track_id = conn.execute(
                """
                INSERT INTO gpx_tracks
                (name, project_id, original_filename, imported_at, point_count)
                VALUES ('Track', 1, 'track.gpx', 2, 1)
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO gpx_points
                (track_id, sequence, latitude, longitude, elevation, recorded_at)
                VALUES (?, 0, 46.5, 7.5, 1200, 3)
                """,
                (track_id,),
            )
            conn.commit()

        content = self.export_backup(False)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            database_bytes = archive.read("OFFLINE360_STUDIO.db")
        database_copy = Path(self.temp_dir.name) / "gps-gpx-backup.db"
        database_copy.write_bytes(database_bytes)
        with closing(sqlite3.connect(database_copy)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT latitude, longitude, gps_source FROM media"
                ).fetchone(),
                (46.5, 7.5, "manual"),
            )
            self.assertEqual(
                conn.execute("SELECT name, point_count FROM gpx_tracks").fetchone(),
                ("Track", 1),
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gpx_points").fetchone()[0], 1)

    def test_restore_replaces_database_and_creates_full_safety_backup(self) -> None:
        original = self.export_backup(False)
        with panorama_app.db() as conn:
            conn.execute("UPDATE media SET title = 'Vor Restore'")
            conn.commit()
        panorama_app.PHOTO_DIR.joinpath("keep.jpg").write_bytes(b"keep")

        response = self.import_backup(original)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["restart_required"])
        self.assertIn("neu starten", payload["message"])
        self.assertTrue(panorama_app.PHOTO_DIR.joinpath("keep.jpg").exists())

        with panorama_app.db() as conn:
            self.assertEqual(conn.execute("SELECT title FROM media").fetchone()[0], "Original")

        safety_path = panorama_app.DATA_DIR / "backups" / payload["safety_backup"]
        self.assertTrue(safety_path.is_file())
        with zipfile.ZipFile(safety_path) as archive:
            self.assertIn("media/photos/keep.jpg", archive.namelist())
            database_bytes = archive.read("OFFLINE360_STUDIO.db")
        safety_db = Path(self.temp_dir.name) / "safety.db"
        safety_db.write_bytes(database_bytes)
        with closing(sqlite3.connect(safety_db)) as conn:
            self.assertEqual(conn.execute("SELECT title FROM media").fetchone()[0], "Vor Restore")

    def test_restore_with_media_replaces_media_directory(self) -> None:
        content = self.export_backup(True)
        panorama_app.PHOTO_DIR.joinpath("obsolete.jpg").write_bytes(b"obsolete")
        panorama_app.PHOTO_DIR.joinpath("tour", "pano.jpg").write_bytes(b"changed")
        response = self.import_backup(content)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertFalse(panorama_app.PHOTO_DIR.joinpath("obsolete.jpg").exists())
        self.assertEqual(
            panorama_app.PHOTO_DIR.joinpath("tour", "pano.jpg").read_bytes(),
            b"photo",
        )

    def test_zip_slip_is_rejected(self) -> None:
        content = self.rewrite_archive(
            self.export_backup(False), extras=[("../escape.txt", b"attack")]
        )
        self.assert_error(self.import_backup(content), 400, "unsafe_archive_path")

    def test_missing_manifest_is_rejected(self) -> None:
        content = self.rewrite_archive(
            self.export_backup(False), skip={"manifest.json"}
        )
        self.assert_error(self.import_backup(content), 400, "manifest_missing")

    def test_wrong_backup_version_is_rejected(self) -> None:
        source = self.export_backup(False)
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        manifest["backup_version"] = 999
        content = self.rewrite_archive(
            source,
            replacements={"manifest.json": json.dumps(manifest).encode("utf-8")},
        )
        self.assert_error(
            self.import_backup(content), 400, "backup_version_unsupported"
        )

    def test_corrupt_zip_and_non_zip_extension_are_rejected(self) -> None:
        self.assert_error(self.import_backup(b"not a zip"), 400, "archive_corrupt")
        self.assert_error(
            self.import_backup(b"not a zip", "backup.txt"), 415, "invalid_file_type"
        )

    def test_corrupt_database_inside_valid_zip_is_rejected(self) -> None:
        content = self.rewrite_archive(
            self.export_backup(False),
            replacements={"OFFLINE360_STUDIO.db": b"not a sqlite database"},
        )
        self.assert_error(
            self.import_backup(content), 400, "checksum_mismatch"
        )

    def test_symlink_entry_is_rejected(self) -> None:
        source = self.export_backup(True)
        link = zipfile.ZipInfo("media/photos/link.jpg")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        content = self.rewrite_archive(source, extras=[(link, b"target.jpg")])
        self.assert_error(self.import_backup(content), 400, "symlink_not_allowed")

    def test_import_requires_a_file_and_export_requires_boolean(self) -> None:
        self.assert_error(
            self.client.post("/api/backup/import"), 400, "backup_file_missing"
        )
        self.assert_error(
            self.client.post("/api/backup/export", json={"includes_media": "yes"}),
            400,
            "invalid_request",
        )


class BackupAssetTests(unittest.TestCase):
    def test_backup_ui_uses_safe_text_and_custom_confirmation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        page = (root / "static" / "index.html").read_text(encoding="utf-8")
        source = (root / "static" / "js" / "backup.js").read_text(encoding="utf-8")
        self.assertIn('id="backupTitle"', page)
        self.assertIn('id="restoreConfirmDialog"', page)
        self.assertIn('role="status"', page)
        self.assertIn("textContent", source)
        self.assertIn("XMLHttpRequest", source)
        self.assertNotIn(".innerHTML", source)
        self.assertNotIn("alert(", source)


if __name__ == "__main__":
    unittest.main()

