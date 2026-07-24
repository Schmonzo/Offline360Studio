from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as panorama_app
from core import gps, gpx


GPX_11 = """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Alpenrunde</name>
    <trkseg>
      <trkpt lat="46.1" lon="7.1"><ele>1200.5</ele><time>2026-06-01T10:00:00Z</time></trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="46.2" lon="7.2"><time>2026-06-01T10:05:00+00:00</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""

GPX_10 = """<?xml version="1.0"?>
<gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/0">
  <trk><name>Altformat</name><trkseg>
    <trkpt lat="-33.2" lon="151.1"><ele>4</ele></trkpt>
  </trkseg></trk>
</gpx>
"""


class GpsGpxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        media_dir = root / "media"
        self.path_patch = patch.multiple(
            panorama_app,
            BASE_DIR=root,
            DATA_DIR=root / "data",
            CONFIG_DIR=root / "data" / "config",
            MEDIA_DIR=media_dir,
            PHOTO_DIR=media_dir / "photos",
            VIDEO_DIR=media_dir / "videos",
            THUMB_DIR=media_dir / "thumbs",
            DB_PATH=root / "data" / "OFFLINE360_STUDIO.db",
        )
        self.path_patch.start()
        panorama_app.app.config.update(TESTING=True)
        panorama_app.init_db()
        self.client = panorama_app.app.test_client()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def add_media(
        self,
        *,
        title: str = "Foto",
        visible: int = 1,
        captured_at: float | None = None,
        source: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> int:
        with panorama_app.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO media
                (type, file_path, title, project, visible, captured_at,
                 latitude, longitude, gps_source, created_at, updated_at)
                VALUES ('photo', ?, ?, 'Default', ?, ?, ?, ?, ?, 1, 1)
                """,
                (
                    f"media/{title}-{captured_at}-{source}.jpg",
                    title,
                    visible,
                    captured_at,
                    latitude,
                    longitude,
                    source,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def import_gpx(
        self,
        xml: str = GPX_11,
        *,
        filename: str = "track.gpx",
        project_id: int | None = None,
    ):
        data = {"file": (io.BytesIO(xml.encode()), filename)}
        if project_id is not None:
            data["project_id"] = str(project_id)
        return self.client.post(
            "/api/gpx/import",
            data=data,
            content_type="multipart/form-data",
        )

    def assert_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json()["error"]["code"], code)

    def test_schema_migration_is_idempotent(self) -> None:
        panorama_app.init_db()
        panorama_app.init_db()
        with panorama_app.db() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(media)").fetchall()
            }
            self.assertTrue(
                {
                    "captured_at",
                    "latitude",
                    "longitude",
                    "altitude",
                    "gps_source",
                    "gps_updated_at",
                }.issubset(columns)
            )
            self.assertEqual(
                conn.execute(
                    "PRAGMA foreign_key_list(gpx_points)"
                ).fetchone()["on_delete"],
                "CASCADE",
            )
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(gpx_points)").fetchall()
            }
            self.assertIn("idx_gpx_points_track_sequence", indexes)
            media_id = self.add_media()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE media SET gps_source='camera' WHERE id=?", (media_id,)
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE media SET latitude=100 WHERE id=?", (media_id,)
                )

    def test_old_media_schema_is_migrated(self) -> None:
        migration_db = Path(self.temp_dir.name) / "migration.db"
        migration_conn = sqlite3.connect(migration_db)
        try:
            conn = migration_conn
            conn.execute(
                """
                CREATE TABLE media (
                    id INTEGER PRIMARY KEY,
                    type TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            migration_conn.close()
        with patch.object(panorama_app, "DB_PATH", migration_db):
            panorama_app.init_db()
            panorama_app.init_db()
            with panorama_app.db() as conn:
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(media)").fetchall()
                }
        self.assertTrue(
            {"latitude", "longitude", "altitude", "gps_source", "gps_updated_at"}.issubset(
                columns
            )
        )

    def test_manual_gps_save_delete_and_validation(self) -> None:
        media_id = self.add_media()
        response = self.client.patch(
            f"/api/media/{media_id}/gps",
            json={"latitude": 46.5, "longitude": 8.25, "altitude": 1234.5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["item"]["gps_source"], "manual")
        with panorama_app.db() as conn:
            row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
            self.assertEqual(row["latitude"], 46.5)
            self.assertIsNotNone(row["gps_updated_at"])

        for payload in (
            {"latitude": 91, "longitude": 0},
            {"latitude": 0, "longitude": -181},
            {"latitude": True, "longitude": 1},
            {"latitude": 1, "longitude": 1, "altitude": float("inf")},
            {"latitude": 1, "longitude": 1, "gps_source": "exif"},
        ):
            self.assert_error(
                self.client.patch(f"/api/media/{media_id}/gps", json=payload),
                400,
                "invalid_gps_source" if payload.get("gps_source") == "exif" else "invalid_gps",
            )

        deleted = self.client.delete(f"/api/media/{media_id}/gps")
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(deleted.get_json()["item"]["latitude"])

    def test_dms_conversion_and_references(self) -> None:
        self.assertAlmostEqual(gps.dms_to_decimal((46, 30, 0), "N"), 46.5)
        self.assertAlmostEqual(gps.dms_to_decimal((46, 30, 0), "S"), -46.5)
        self.assertAlmostEqual(gps.dms_to_decimal((7, 15, 30), "E"), 7.258333333)
        self.assertAlmostEqual(gps.dms_to_decimal((7, 15, 30), "W"), -7.258333333)
        with self.assertRaises(ValueError):
            gps.dms_to_decimal((1, 60, 0), "N")

    def test_exif_altitude_reference_is_applied(self) -> None:
        class FakeExif(dict):
            def get_ifd(self, ifd):
                if ifd == gps.ExifTags.IFD.GPSInfo:
                    return {
                        1: "N",
                        2: (46, 30, 0),
                        3: "E",
                        4: (7, 15, 0),
                        5: b"\x01",
                        6: 25,
                    }
                return {}

        class FakeImage:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def getexif(self):
                return FakeExif()

        with patch.object(gps.Image, "open", return_value=FakeImage()):
            metadata = gps.read_photo_metadata(Path("photo.jpg"))
        self.assertEqual(metadata["altitude"], -25)
        self.assertEqual(metadata["gps_source"], "exif")

    def test_rescan_imports_exif_but_preserves_manual_and_gpx(self) -> None:
        photo = panorama_app.PHOTO_DIR / "scan.jpg"
        photo.parent.mkdir(parents=True, exist_ok=True)
        panorama_app.Image.new("RGB", (8, 4), (20, 30, 40)).save(photo, "JPEG")
        first = {
            "latitude": 46.0,
            "longitude": 7.0,
            "altitude": -12.0,
            "gps_source": "exif",
            "captured_at": 1000.0,
        }
        with patch.object(panorama_app.gps, "read_photo_metadata", return_value=first):
            panorama_app.scan_media()
        with panorama_app.db() as conn:
            row = conn.execute("SELECT * FROM media").fetchone()
            media_id = row["id"]
            self.assertEqual(row["gps_source"], "exif")
            conn.execute(
                """
                UPDATE media SET latitude=1, longitude=2, gps_source='manual'
                WHERE id=?
                """,
                (media_id,),
            )
            conn.commit()
        changed = {**first, "latitude": 48.0, "longitude": 9.0}
        with patch.object(panorama_app.gps, "read_photo_metadata", return_value=changed):
            panorama_app.scan_media()
        with panorama_app.db() as conn:
            row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
            self.assertEqual((row["latitude"], row["longitude"]), (1, 2))
            conn.execute(
                "UPDATE media SET gps_source='gpx' WHERE id=?", (media_id,)
            )
            conn.commit()
        with patch.object(panorama_app.gps, "read_photo_metadata", return_value=changed):
            panorama_app.scan_media()
        with panorama_app.db() as conn:
            row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
            self.assertEqual((row["latitude"], row["longitude"]), (1, 2))

    def test_gpx_10_11_multiple_segments_and_crud(self) -> None:
        response = self.import_gpx()
        self.assertEqual(response.status_code, 201)
        track = response.get_json()["item"]
        self.assertEqual(track["name"], "Alpenrunde")
        self.assertEqual(track["point_count"], 2)

        second = self.import_gpx(GPX_10, filename="legacy.gpx")
        self.assertEqual(second.status_code, 201)
        listed = self.client.get("/api/gpx/tracks").get_json()["items"]
        self.assertEqual([item["name"] for item in listed], ["Alpenrunde", "Altformat"])

        detail = self.client.get(f"/api/gpx/tracks/{track['id']}").get_json()["item"]
        self.assertEqual([point["sequence"] for point in detail["points"]], [0, 1])
        self.assertEqual(detail["points"][0]["elevation"], 1200.5)
        self.assertIsNotNone(detail["points"][0]["recorded_at"])

        self.assertEqual(
            self.client.delete(f"/api/gpx/tracks/{track['id']}").status_code, 200
        )
        with panorama_app.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM gpx_points WHERE track_id=?", (track["id"],)
            ).fetchone()[0]
            self.assertEqual(count, 0)

    def test_gpx_rejects_invalid_and_unsafe_data_transactionally(self) -> None:
        cases = (
            ("<gpx>", "invalid_xml"),
            ('<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///etc/passwd">]><gpx/>', "unsafe_xml"),
            (
                '<gpx><trk><trkseg><trkpt lat="91" lon="0"/></trkseg></trk></gpx>',
                "invalid_coordinate",
            ),
            (
                '<gpx><trk><trkseg><trkpt lat="1" lon="2"><time>today</time></trkpt></trkseg></trk></gpx>',
                "invalid_time",
            ),
        )
        for xml, code in cases:
            self.assert_error(self.import_gpx(xml), 400, code)
        with panorama_app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gpx_tracks").fetchone()[0], 0)
        self.assert_error(self.import_gpx(GPX_11, filename="track.xml"), 415, "invalid_file_type")

    def test_gpx_point_limit(self) -> None:
        original = gpx.parse_gpx
        with patch.object(
            panorama_app.gpx,
            "parse_gpx",
            side_effect=lambda path: original(path, max_points=1),
        ):
            self.assert_error(self.import_gpx(), 400, "point_limit_exceeded")

    def test_gpx_upload_size_limit(self) -> None:
        target = Path(self.temp_dir.name) / "oversize.gpx"
        with patch.object(gpx, "MAX_GPX_FILE_SIZE", 3):
            with self.assertRaises(gpx.GpxError) as raised:
                gpx.save_upload(io.BytesIO(b"1234"), target)
        self.assertEqual(raised.exception.code, "gpx_file_too_large")

    def test_match_media_respects_sources_window_and_project(self) -> None:
        track = self.import_gpx().get_json()["item"]
        first_time = self.client.get(
            f"/api/gpx/tracks/{track['id']}"
        ).get_json()["item"]["points"][0]["recorded_at"]
        project = self.client.post("/api/projects", json={"name": "Tour"}).get_json()["item"]
        matched = self.add_media(title="match", captured_at=first_time + 20)
        existing_gpx = self.add_media(
            title="update",
            captured_at=first_time,
            source="gpx",
            latitude=1,
            longitude=2,
        )
        manual = self.add_media(
            title="manual",
            captured_at=first_time,
            source="manual",
            latitude=3,
            longitude=4,
        )
        outside = self.add_media(title="outside", captured_at=first_time + 10_000)
        no_time = self.add_media(title="no-time")
        for media_id in (matched, existing_gpx, manual, outside, no_time):
            response = self.client.post(
                f"/api/projects/{project['id']}/media", json={"media_id": media_id}
            )
            self.assertEqual(response.status_code, 201)
        unrelated = self.add_media(title="unrelated", captured_at=first_time)

        response = self.client.post(
            f"/api/gpx/tracks/{track['id']}/match-media",
            json={
                "max_time_difference_seconds": 300,
                "project_id": project["id"],
            },
        )
        result = response.get_json()
        self.assertEqual(
            (result["matched"], result["skipped"], result["unmatched"]), (2, 2, 1)
        )
        self.assertEqual(len(result["details"]), 5)
        with panorama_app.db() as conn:
            rows = {
                row["id"]: row
                for row in conn.execute(
                    "SELECT id, latitude, longitude, gps_source FROM media"
                ).fetchall()
            }
        self.assertEqual(rows[matched]["gps_source"], "gpx")
        self.assertEqual(rows[existing_gpx]["latitude"], 46.1)
        self.assertEqual(rows[manual]["latitude"], 3)
        self.assertIsNone(rows[outside]["gps_source"])
        self.assertIsNone(rows[unrelated]["gps_source"])

    def test_map_and_track_project_filters(self) -> None:
        visible = self.add_media(title="visible")
        hidden = self.add_media(title="hidden", visible=0)
        for media_id in (visible, hidden):
            self.client.patch(
                f"/api/media/{media_id}/gps",
                json={"latitude": 46, "longitude": 7},
            )
        project = self.client.post("/api/projects", json={"name": "Tour"}).get_json()["item"]
        self.client.post(
            f"/api/projects/{project['id']}/media", json={"media_id": visible}
        )
        project_track = self.import_gpx(project_id=project["id"]).get_json()["item"]
        self.import_gpx(GPX_10)

        media = self.client.get(
            f"/api/map/media?project_id={project['id']}"
        ).get_json()["items"]
        self.assertEqual([item["id"] for item in media], [visible])
        tracks = self.client.get(
            f"/api/gpx/tracks?project_id={project['id']}"
        ).get_json()["items"]
        self.assertEqual([item["id"] for item in tracks], [project_track["id"]])
        self.assert_error(self.client.get("/api/map/media?project_id=no"), 400, "invalid_project_id")

    def test_gpx_foreign_keys(self) -> None:
        with panorama_app.db() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO gpx_points
                    (track_id, sequence, latitude, longitude)
                    VALUES (999, 0, 1, 2)
                    """
                )

