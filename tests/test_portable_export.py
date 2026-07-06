from __future__ import annotations

import io
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as panorama_app
from core import portable_export


class PortableExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        data_dir = root / "data"
        media_dir = root / "media"
        portable_server = root / "tools" / "portable-server" / "server.exe"
        self.path_patch = patch.multiple(
            panorama_app,
            DATA_DIR=data_dir,
            CONFIG_DIR=data_dir / "config",
            MEDIA_DIR=media_dir,
            PHOTO_DIR=media_dir / "photos",
            VIDEO_DIR=media_dir / "videos",
            THUMB_DIR=media_dir / "thumbs",
            DB_PATH=data_dir / "panorama_studio.db",
            MAPS_DIR=data_dir / "maps",
            PORTABLE_SERVER_EXE=portable_server,
        )
        self.path_patch.start()
        panorama_app.app.config.update(TESTING=True)
        panorama_app.init_db()
        for directory in (
            panorama_app.PHOTO_DIR,
            panorama_app.VIDEO_DIR,
            panorama_app.THUMB_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        portable_server.parent.mkdir(parents=True, exist_ok=True)
        portable_server.write_bytes(b"MZ-test-portable-server")
        portable_server.with_name("server.exe.sha256").write_text(
            f"{hashlib.sha256(portable_server.read_bytes()).hexdigest()}  server.exe\n",
            encoding="ascii",
        )
        self.portable_server = portable_server
        (panorama_app.PHOTO_DIR / "first.jpg").write_bytes(b"first-photo")
        (panorama_app.PHOTO_DIR / "second.jpg").write_bytes(b"second-photo")
        (panorama_app.VIDEO_DIR / "clip.mp4").write_bytes(b"video")
        (panorama_app.THUMB_DIR / "first.jpg").write_bytes(b"thumb")
        with panorama_app.db() as conn:
            conn.execute(
                """
                INSERT INTO projects
                (id, name, description, cover_media_id, start_media_id, created_at, updated_at)
                VALUES (1, 'Meine Tour', 'Beschreibung', NULL, NULL, 1, 1)
                """
            )
            self.first = self._insert_media(
                conn,
                "photo",
                "media/photos/first.jpg",
                "Erstes",
                thumb_path="media/thumbs/first.jpg",
                start_yaw=0.25,
                start_pitch=-0.1,
                start_fov=1.2,
                latitude=47.3,
                longitude=8.5,
            )
            self.video = self._insert_media(
                conn, "video", "media/videos/clip.mp4", "Video"
            )
            self.second = self._insert_media(
                conn, "photo", "media/photos/second.jpg", "Zweites"
            )
            for order, media_id in enumerate((self.second, self.first, self.video)):
                conn.execute(
                    "INSERT INTO project_media(project_id, media_id, sort_order) VALUES (1, ?, ?)",
                    (media_id, order),
                )
            conn.execute(
                "UPDATE projects SET cover_media_id = ?, start_media_id = ? WHERE id = 1",
                (self.first, self.second),
            )
            conn.execute(
                """
                INSERT INTO hotspots
                (source_media_id, action_type, yaw, pitch, title, info_text,
                 target_media_id, visible, created_at, updated_at)
                VALUES (?, 'panorama', 0.5, -0.2, 'Weiter', '', ?, 1, 1, 1)
                """,
                (self.first, self.second),
            )
            conn.execute(
                """
                INSERT INTO hotspots
                (source_media_id, action_type, yaw, pitch, title, info_text,
                 target_media_id, visible, created_at, updated_at)
                VALUES (?, 'info', -0.4, 0.1, 'Info', 'Text', NULL, 1, 1, 1)
                """,
                (self.first,),
            )
            cursor = conn.execute(
                """
                INSERT INTO gpx_tracks(name, project_id, original_filename, imported_at, point_count)
                VALUES ('Route', 1, 'route.gpx', 1, 2)
                """
            )
            conn.executemany(
                """
                INSERT INTO gpx_points
                (track_id, sequence, latitude, longitude, elevation, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (cursor.lastrowid, 0, 47.0, 8.0, 500.0, 1.0),
                    (cursor.lastrowid, 1, 47.1, 8.1, 510.0, 2.0),
                ],
            )
            conn.commit()
        self.client = panorama_app.app.test_client()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _insert_media(
        conn,
        media_type,
        file_path,
        title,
        thumb_path=None,
        start_yaw=None,
        start_pitch=None,
        start_fov=None,
        latitude=None,
        longitude=None,
    ):
        cursor = conn.execute(
            """
            INSERT INTO media
            (type, file_path, thumb_path, title, project, description,
             start_yaw, start_pitch, start_fov, latitude, longitude,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Default', ?, ?, ?, ?, ?, ?, 1, 1)
            """,
            (
                media_type,
                file_path,
                thumb_path,
                title,
                f"{title} Beschreibung",
                start_yaw,
                start_pitch,
                start_fov,
                latitude,
                longitude,
            ),
        )
        return int(cursor.lastrowid)

    def export(self, **overrides):
        payload = {
            "project_id": 1,
            "filename": "meine-tour",
            "include_videos": True,
            "include_map": False,
            "include_tracks": True,
        }
        payload.update(overrides)
        response = self.client.post("/api/export/portable-tour", json=payload)
        content = response.get_data()
        response.close()
        return response, content

    @staticmethod
    def open_archive(content):
        return zipfile.ZipFile(io.BytesIO(content))

    def test_export_requires_existing_project_and_valid_request(self) -> None:
        response, _ = self.export(project_id=999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "project_not_found")
        invalid = self.client.post(
            "/api/export/portable-tour",
            json={"project_id": 1, "filename": "x"},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_export_fails_cleanly_without_built_server(self) -> None:
        self.portable_server.unlink()
        response, _ = self.export()
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "portable_server_missing")
        self.assertIn("tools/portable-server/build.ps1", payload["error"]["message"])

    def test_export_rejects_missing_or_mismatched_server_hash(self) -> None:
        hash_path = self.portable_server.with_name("server.exe.sha256")
        hash_path.unlink()
        response, _ = self.export()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "portable_server_hash_missing",
        )
        hash_path.write_text(f"{'0' * 64}  server.exe\n", encoding="ascii")
        response, _ = self.export()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "portable_server_hash_mismatch",
        )

    def test_zip_structure_order_start_view_hotspots_and_paths(self) -> None:
        response, content = self.export(filename="../../Meine Tour?.zip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertIn('filename="Meine-Tour.zip"', response.headers["Content-Disposition"])
        with self.open_archive(content) as archive:
            names = set(archive.namelist())
            for name in (
                "portable-tour/index.html",
                "portable-tour/tour.json",
                "portable-tour/README.txt",
                "portable-tour/VERSION.txt",
                "portable-tour/start-tour.bat",
                "portable-tour/server.exe",
                "portable-tour/assets/css/viewer.css",
                "portable-tour/assets/js/viewer.js",
                "portable-tour/assets/lib/marzipano.js",
            ):
                self.assertIn(name, names)
            self.assertEqual(
                archive.read("portable-tour/server.exe"),
                self.portable_server.read_bytes(),
            )
            tour = json.loads(archive.read("portable-tour/tour.json"))
            version = archive.read("portable-tour/VERSION.txt").decode("ascii").strip()
            readme = archive.read("portable-tour/README.txt").decode("utf-8")
            self.assertEqual(tour["version"], portable_export.EXPORT_VERSION)
            self.assertEqual(version, portable_export.EXPORT_VERSION)
            self.assertIn(portable_export.EXPORT_VERSION, readme)
            self.assertEqual(tour["media_order"], [self.second, self.first, self.video])
            self.assertEqual(tour["project"]["start_media_id"], self.second)
            self.assertEqual(tour["project"]["cover_media_id"], self.first)
            first = next(item for item in tour["media"] if item["id"] == self.first)
            self.assertEqual(first["start_view"], {"yaw": 0.25, "pitch": -0.1, "fov": 1.2})
            self.assertEqual([item["action_type"] for item in first["hotspots"]], ["panorama", "info"])
            self.assertEqual(first["gps"]["latitude"], 47.3)
            serialized = json.dumps(tour)
            self.assertNotIn(str(self.temp_dir.name), serialized)
            self.assertFalse(any(Path(item["local_path"]).is_absolute() for item in tour["media"]))

    def test_video_and_gpx_options(self) -> None:
        _, content = self.export(include_videos=False, include_tracks=False)
        with self.open_archive(content) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            self.assertNotIn(self.video, tour["media_order"])
            self.assertEqual(tour["gpx_tracks"], [])
            self.assertFalse(any(name.endswith(".mp4") for name in archive.namelist()))
            self.assertFalse(any(name.endswith("-Route.json") for name in archive.namelist()))
        _, content = self.export(include_videos=True, include_tracks=True)
        with self.open_archive(content) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            self.assertIn(self.video, tour["media_order"])
            self.assertEqual(len(tour["gpx_tracks"]), 1)
            self.assertEqual(len(tour["gpx_tracks"][0]["points"]), 2)

    def test_map_option_packages_active_raster_and_vector_mbtiles(self) -> None:
        map_file = panorama_app.MAPS_DIR / "source.mbtiles"
        with closing(sqlite3.connect(map_file)) as conn:
            conn.execute("CREATE TABLE tiles (zoom_level, tile_column, tile_row, tile_data)")
        with panorama_app.db() as conn:
            conn.execute(
                """
                INSERT INTO map_sources
                (id, name, filename, format, map_type, active, imported_at)
                VALUES (1, 'Offline', 'source.mbtiles', 'png', 'raster', 1, 1)
                """
            )
            conn.commit()
        _, without_map = self.export(include_map=False)
        with self.open_archive(without_map) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            self.assertIsNone(tour["map_source"])
            self.assertFalse(any(name.endswith(".mbtiles") for name in archive.namelist()))
        _, with_map = self.export(include_map=True)
        with self.open_archive(with_map) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            self.assertEqual(tour["map_source"]["map_type"], "raster")
            self.assertEqual(
                set(tour["map_source"]),
                {
                    "path",
                    "map_type",
                    "format",
                    "name",
                    "attribution",
                    "bounds",
                    "center",
                    "min_zoom",
                    "max_zoom",
                },
            )
            self.assertFalse(Path(tour["map_source"]["path"]).is_absolute())
            self.assertTrue(any(name.endswith(".mbtiles") for name in archive.namelist()))
        with panorama_app.db() as conn:
            conn.execute(
                "UPDATE map_sources SET format = 'pbf', map_type = 'vector' WHERE id = 1"
            )
            conn.commit()
        _, vector_map = self.export(include_map=True)
        with self.open_archive(vector_map) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            self.assertEqual(tour["map_source"]["map_type"], "vector")
            self.assertIn("portable-tour/assets/lib/maplibre-gl.js", archive.namelist())

    def test_server_hash_and_start_script_are_packaged_without_runtime_dependencies(self) -> None:
        digest = hashlib.sha256(self.portable_server.read_bytes()).hexdigest()
        hash_path = self.portable_server.with_name("server.exe.sha256")
        hash_path.write_text(f"{digest}  server.exe\n", encoding="ascii")
        _, content = self.export()
        with self.open_archive(content) as archive:
            names = set(archive.namelist())
            self.assertIn("portable-tour/server.exe", names)
            self.assertIn("portable-tour/server.exe.sha256", names)
            batch = archive.read("portable-tour/start-tour.bat").decode("utf-8").lower()
            self.assertIn("server.exe", batch)
            for forbidden in ("python", "node", "java", "powershell", "http://", "https://"):
                self.assertNotIn(forbidden, batch)

    def test_missing_and_unsafe_media_paths_are_not_copied(self) -> None:
        outside = Path(self.temp_dir.name) / "secret.jpg"
        outside.write_bytes(b"secret")
        with panorama_app.db() as conn:
            conn.execute(
                "UPDATE media SET file_path = ? WHERE id = ?",
                ("../secret.jpg", self.first),
            )
            conn.execute(
                "UPDATE media SET file_path = ? WHERE id = ?",
                ("media/photos/missing.jpg", self.second),
            )
            conn.commit()
        with self.assertLogs("core.portable_export", level="WARNING") as logs:
            _, content = self.export()
        self.assertGreaterEqual(len(logs.output), 2)
        with self.open_archive(content) as archive:
            tour = json.loads(archive.read("portable-tour/tour.json"))
            affected = [item for item in tour["media"] if item["id"] in (self.first, self.second)]
            self.assertTrue(all(not item["available"] and item["local_path"] is None for item in affected))
            self.assertNotIn(b"secret", content)

    def test_export_has_no_external_runtime_urls_and_cleans_temporary_directory(self) -> None:
        created = []
        real_temporary_directory = tempfile.TemporaryDirectory

        def tracked_directory(*args, **kwargs):
            instance = real_temporary_directory(*args, **kwargs)
            created.append(Path(instance.name))
            return instance

        with patch.object(panorama_app.tempfile, "TemporaryDirectory", tracked_directory):
            response, content = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))
        with self.open_archive(content) as archive:
            runtime_names = [
                "portable-tour/index.html",
                "portable-tour/tour.json",
                "portable-tour/assets/css/viewer.css",
                "portable-tour/assets/js/viewer.js",
                "portable-tour/assets/js/video360.js",
                "portable-tour/assets/js/tinyplanet.js",
            ]
            runtime = b"\n".join(archive.read(name) for name in runtime_names).lower()
            self.assertNotIn(b"https://", runtime)
            self.assertNotIn(b"http://", runtime)

    def test_admin_ui_contains_export_controls(self) -> None:
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        response.close()
        for control_id in (
            "portableExportProject",
            "portableExportFilename",
            "portableExportZip",
            "portableExportVideos",
            "portableExportMap",
            "portableExportTracks",
            "portableExportBtn",
            "portableExportStatus",
            "portableExportError",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn("/static/js/portable_export.js", html)


if __name__ == "__main__":
    unittest.main()
