from __future__ import annotations

import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as panorama_app


class HotspotApiTests(unittest.TestCase):
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
        self.source_photo_id = self.add_media("photo", "source.jpg")
        self.target_photo_id = self.add_media("photo", "target.jpg")
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

    def assert_api_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], code)
        self.assertIsInstance(payload["error"]["message"], str)

    def create_hotspot(self, payload: dict, source_id: int | None = None):
        source_id = source_id or self.source_photo_id
        return self.client.post(
            f"/api/media/{source_id}/hotspots",
            json=payload,
        )

    def test_migration_is_idempotent_and_enables_foreign_keys(self) -> None:
        panorama_app.init_db()
        panorama_app.init_db()

        with panorama_app.db() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            table = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='hotspots'"
            ).fetchone()
            self.assertIsNotNone(table)
            self.assertIn("CHECK (action_type IN ('panorama', 'info'))", table["sql"])
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(hotspots)").fetchall()
            }
            self.assertIn("idx_hotspots_source_media_id", indexes)
            self.assertIn("idx_hotspots_target_media_id", indexes)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO hotspots
                    (source_media_id, action_type, yaw, pitch, created_at, updated_at)
                    VALUES (?, 'invalid', 0, 0, 1, 1)
                    """,
                    (self.source_photo_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO hotspots
                    (source_media_id, action_type, yaw, pitch, created_at, updated_at)
                    VALUES (99999, 'info', 0, 0, 1, 1)
                    """
                )

    def test_info_hotspot_crud(self) -> None:
        created = self.create_hotspot(
            {
                "action_type": "info",
                "yaw": 0.5,
                "pitch": -0.25,
                "title": "Details",
                "info_text": "Beschreibung",
            }
        )
        self.assertEqual(created.status_code, 201)
        hotspot = created.get_json()["item"]
        hotspot_id = hotspot["id"]
        self.assertIsNone(hotspot["target_media_id"])

        listed = self.client.get(
            f"/api/media/{self.source_photo_id}/hotspots"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([hotspot_id], [item["id"] for item in listed.get_json()["items"]])

        updated = self.client.patch(
            f"/api/hotspots/{hotspot_id}",
            json={
                "pitch": 0.2,
                "title": "Neue Details",
                "visible": False,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["item"]["pitch"], 0.2)
        self.assertEqual(updated.get_json()["item"]["visible"], 0)

        deleted = self.client.delete(f"/api/hotspots/{hotspot_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json()["status"], "ok")
        self.assertEqual(
            self.client.get(
                f"/api/media/{self.source_photo_id}/hotspots"
            ).get_json()["items"],
            [],
        )

    def test_panorama_hotspot_crud(self) -> None:
        created = self.create_hotspot(
            {
                "action_type": "panorama",
                "yaw": -1.0,
                "pitch": 0.1,
                "title": "Weiter",
                "target_media_id": self.target_photo_id,
            }
        )
        self.assertEqual(created.status_code, 201)
        hotspot = created.get_json()["item"]
        self.assertEqual(hotspot["target_media_id"], self.target_photo_id)

        updated = self.client.patch(
            f"/api/hotspots/{hotspot['id']}",
            json={"yaw": 1.25, "title": "Zur nÃ¤chsten Ansicht"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["item"]["yaw"], 1.25)

        deleted = self.client.delete(f"/api/hotspots/{hotspot['id']}")
        self.assertEqual(deleted.status_code, 200)

    def test_rejects_invalid_action_types(self) -> None:
        response = self.create_hotspot(
            {"action_type": "link", "yaw": 0, "pitch": 0}
        )
        self.assert_api_error(response, 400, "invalid_action_type")

    def test_rejects_invalid_coordinates(self) -> None:
        invalid_payloads = [
            {"action_type": "info", "yaw": "0", "pitch": 0},
            {"action_type": "info", "yaw": True, "pitch": 0},
            {"action_type": "info", "yaw": float("inf"), "pitch": 0},
            {"action_type": "info", "yaw": 0, "pitch": math.pi / 2 + 0.01},
        ]
        expected_codes = [
            "invalid_coordinates",
            "invalid_coordinates",
            "invalid_coordinates",
            "invalid_pitch",
        ]
        for payload, code in zip(invalid_payloads, expected_codes):
            with self.subTest(payload=payload):
                response = self.create_hotspot(payload)
                self.assert_api_error(response, 400, code)

    def test_rejects_unknown_media(self) -> None:
        response = self.create_hotspot(
            {"action_type": "info", "yaw": 0, "pitch": 0},
            source_id=99999,
        )
        self.assert_api_error(response, 404, "media_not_found")

        response = self.create_hotspot(
            {
                "action_type": "panorama",
                "yaw": 0,
                "pitch": 0,
                "target_media_id": 99999,
            }
        )
        self.assert_api_error(response, 404, "target_media_not_found")

    def test_rejects_videos_as_source_or_target(self) -> None:
        response = self.create_hotspot(
            {"action_type": "info", "yaw": 0, "pitch": 0},
            source_id=self.video_id,
        )
        self.assert_api_error(response, 400, "invalid_source_media")

        response = self.create_hotspot(
            {
                "action_type": "panorama",
                "yaw": 0,
                "pitch": 0,
                "target_media_id": self.video_id,
            }
        )
        self.assert_api_error(response, 400, "invalid_target_media")

    def test_info_hotspot_rejects_target_media(self) -> None:
        response = self.create_hotspot(
            {
                "action_type": "info",
                "yaw": 0,
                "pitch": 0,
                "target_media_id": self.target_photo_id,
            }
        )
        self.assert_api_error(response, 400, "invalid_target_media")

    def test_foreign_key_delete_behavior(self) -> None:
        info = self.create_hotspot(
            {"action_type": "info", "yaw": 0, "pitch": 0}
        ).get_json()["item"]
        panorama = self.create_hotspot(
            {
                "action_type": "panorama",
                "yaw": 0,
                "pitch": 0,
                "target_media_id": self.target_photo_id,
            }
        ).get_json()["item"]

        with panorama_app.db() as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (self.target_photo_id,))
            conn.commit()
            target = conn.execute(
                "SELECT target_media_id FROM hotspots WHERE id = ?",
                (panorama["id"],),
            ).fetchone()
            self.assertIsNone(target["target_media_id"])

            conn.execute("DELETE FROM media WHERE id = ?", (self.source_photo_id,))
            conn.commit()
            remaining = conn.execute(
                "SELECT id FROM hotspots WHERE id IN (?, ?)",
                (info["id"], panorama["id"]),
            ).fetchall()
            self.assertEqual(remaining, [])

    def test_unknown_hotspot_uses_json_error_format(self) -> None:
        self.assert_api_error(
            self.client.patch("/api/hotspots/99999", json={"title": "x"}),
            404,
            "hotspot_not_found",
        )
        self.assert_api_error(
            self.client.delete("/api/hotspots/99999"),
            404,
            "hotspot_not_found",
        )

    def test_existing_media_upload_and_rescan_endpoints_still_work(self) -> None:
        media_response = self.client.get("/api/media")
        self.assertEqual(media_response.status_code, 200)
        self.assertEqual(len(media_response.get_json()["items"]), 3)

        rescan_response = self.client.post("/api/rescan")
        self.assertEqual(rescan_response.status_code, 200)
        self.assertEqual(rescan_response.get_json()["status"], "ok")

        upload_response = self.client.post(
            "/api/upload",
            data={"project": "Default"},
        )
        self.assertEqual(upload_response.status_code, 200)
        self.assertEqual(upload_response.get_json()["saved"], 0)


if __name__ == "__main__":
    unittest.main()

