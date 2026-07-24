from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as panorama_app


class StartViewApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        media_dir = root / "media"
        self.path_patch = patch.multiple(
            panorama_app,
            DATA_DIR=root / "data",
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
        self.photo_id = self.add_media("photo", "panorama.jpg")
        self.video_id = self.add_media("video", "video.mp4")

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def add_media(self, media_type: str, filename: str) -> int:
        with panorama_app.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO media
                (type, file_path, title, project, created_at, updated_at)
                VALUES (?, ?, ?, 'Default', 1, 1)
                """,
                (media_type, f"media/{filename}", filename),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def assert_api_error(self, response, code: str) -> None:
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], code)

    def test_schema_migration_is_idempotent(self) -> None:
        panorama_app.init_db()
        panorama_app.init_db()
        with panorama_app.db() as conn:
            columns = {
                row["name"]: row["type"]
                for row in conn.execute("PRAGMA table_info(media)").fetchall()
            }
        self.assertEqual(columns["start_yaw"], "REAL")
        self.assertEqual(columns["start_pitch"], "REAL")
        self.assertEqual(columns["start_fov"], "REAL")

    def test_save_and_read_start_view(self) -> None:
        start_view = {"yaw": 1.25, "pitch": -0.3, "fov": 1.1}
        response = self.client.put(
            f"/api/media/{self.photo_id}/start-view",
            json=start_view,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["item"],
            {
                "id": self.photo_id,
                "start_yaw": 1.25,
                "start_pitch": -0.3,
                "start_fov": 1.1,
            },
        )

        items = self.client.get("/api/media").get_json()["items"]
        photo = next(item for item in items if item["id"] == self.photo_id)
        self.assertEqual(photo["start_yaw"], 1.25)
        self.assertEqual(photo["start_pitch"], -0.3)
        self.assertEqual(photo["start_fov"], 1.1)

    def test_reset_start_view(self) -> None:
        self.client.put(
            f"/api/media/{self.photo_id}/start-view",
            json={"yaw": 1, "pitch": 0.2, "fov": 1},
        )
        response = self.client.delete(f"/api/media/{self.photo_id}/start-view")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["item"]["start_yaw"])

        items = self.client.get("/api/media").get_json()["items"]
        photo = next(item for item in items if item["id"] == self.photo_id)
        self.assertIsNone(photo["start_yaw"])
        self.assertIsNone(photo["start_pitch"])
        self.assertIsNone(photo["start_fov"])

    def test_rejects_invalid_start_views(self) -> None:
        cases = [
            ({"yaw": "0", "pitch": 0, "fov": 1}, "invalid_start_view"),
            ({"yaw": True, "pitch": 0, "fov": 1}, "invalid_start_view"),
            ({"yaw": math.inf, "pitch": 0, "fov": 1}, "invalid_start_view"),
            ({"yaw": 0, "pitch": math.pi / 2 + 0.01, "fov": 1}, "invalid_pitch"),
            ({"yaw": 0, "pitch": 0, "fov": math.radians(24)}, "invalid_fov"),
            ({"yaw": 0, "pitch": 0, "fov": math.radians(166)}, "invalid_fov"),
            ({"yaw": 0, "pitch": 0}, "invalid_start_view"),
        ]
        for payload, code in cases:
            with self.subTest(payload=payload):
                response = self.client.put(
                    f"/api/media/{self.photo_id}/start-view",
                    json=payload,
                )
                self.assert_api_error(response, code)

    def test_rejects_video_and_unknown_media(self) -> None:
        payload = {"yaw": 0, "pitch": 0, "fov": 1}
        self.assert_api_error(
            self.client.put(
                f"/api/media/{self.video_id}/start-view",
                json=payload,
            ),
            "invalid_media_type",
        )
        response = self.client.put("/api/media/99999/start-view", json=payload)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "media_not_found")


if __name__ == "__main__":
    unittest.main()

