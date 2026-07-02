from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as panorama_app


class ProjectApiTests(unittest.TestCase):
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
            DB_PATH=root / "data" / "panorama_studio.db",
        )
        self.path_patch.start()
        panorama_app.app.config.update(TESTING=True)
        panorama_app.init_db()
        self.client = panorama_app.app.test_client()
        self.photo_a = self.add_media("photo", "a.jpg")
        self.photo_b = self.add_media("photo", "b.jpg")
        self.video = self.add_media("video", "video.mp4")

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

    def create_project(self, name: str = "Tour") -> dict:
        response = self.client.post(
            "/api/projects",
            json={"name": name, "description": "Beschreibung"},
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["item"]

    def add_to_project(self, project_id: int, media_id: int):
        return self.client.post(
            f"/api/projects/{project_id}/media",
            json={"media_id": media_id},
        )

    def assert_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], code)
        self.assertIsInstance(error["message"], str)

    def test_schema_is_idempotent_and_has_foreign_keys_and_index(self) -> None:
        panorama_app.init_db()
        panorama_app.init_db()
        with panorama_app.db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("projects", tables)
            self.assertIn("project_media", tables)
            foreign_keys = conn.execute(
                "PRAGMA foreign_key_list(project_media)"
            ).fetchall()
            self.assertEqual(
                {row["table"]: row["on_delete"] for row in foreign_keys},
                {"projects": "CASCADE", "media": "CASCADE"},
            )
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(project_media)").fetchall()
            }
            self.assertIn("idx_project_media_project_sort", indexes)

            project = self.create_project()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO project_media(project_id, media_id, sort_order)
                    VALUES (?, 99999, 0)
                    """,
                    (project["id"],),
                )

    def test_project_crud_and_required_name(self) -> None:
        self.assert_error(
            self.client.post("/api/projects", json={"name": "  "}),
            400,
            "invalid_name",
        )
        project = self.create_project("  Erste Tour  ")
        self.assertEqual(project["name"], "Erste Tour")
        self.assertEqual(project["description"], "Beschreibung")

        listed = self.client.get("/api/projects")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["items"][0]["media_count"], 0)
        self.assertIsNone(listed.get_json()["items"][0]["cover_media"])

        updated = self.client.patch(
            f"/api/projects/{project['id']}",
            json={"name": "Neue Tour", "description": "Neu"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["item"]["name"], "Neue Tour")

        deleted = self.client.delete(f"/api/projects/{project['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json()["item"]["id"], project["id"])
        self.assert_error(
            self.client.get(f"/api/projects/{project['id']}"),
            404,
            "project_not_found",
        )

    def test_media_assignment_is_ordered_and_allows_multiple_projects(self) -> None:
        first = self.create_project("Erste")
        second = self.create_project("Zweite")
        for media_id in (self.photo_a, self.video, self.photo_b):
            response = self.add_to_project(first["id"], media_id)
            self.assertEqual(response.status_code, 201)
        self.assertEqual(
            [item["id"] for item in response.get_json()["item"]["media"]],
            [self.photo_a, self.video, self.photo_b],
        )
        self.assertEqual(
            [item["sort_order"] for item in response.get_json()["item"]["media"]],
            [0, 1, 2],
        )
        self.assertEqual(
            self.add_to_project(second["id"], self.photo_a).status_code,
            201,
        )
        self.assert_error(
            self.add_to_project(first["id"], self.photo_a),
            400,
            "media_already_assigned",
        )

    def test_reorder_requires_exact_membership_and_remains_stable(self) -> None:
        project = self.create_project()
        for media_id in (self.photo_a, self.video, self.photo_b):
            self.add_to_project(project["id"], media_id)
        order = [self.photo_b, self.photo_a, self.video]
        response = self.client.patch(
            f"/api/projects/{project['id']}/media/order",
            json={"media_ids": order},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.get_json()["item"]["media"]],
            order,
        )
        read_back = self.client.get(f"/api/projects/{project['id']}").get_json()
        self.assertEqual([item["id"] for item in read_back["item"]["media"]], order)
        self.assert_error(
            self.client.patch(
                f"/api/projects/{project['id']}/media/order",
                json={"media_ids": [self.photo_a]},
            ),
            400,
            "invalid_order",
        )
        self.assert_error(
            self.client.patch(
                f"/api/projects/{project['id']}/media/order",
                json={"media_ids": [self.photo_a, self.video, 99999]},
            ),
            404,
            "media_not_found",
        )

    def test_start_panorama_and_cover_must_be_assigned(self) -> None:
        project = self.create_project()
        url = f"/api/projects/{project['id']}"
        self.assert_error(
            self.client.patch(url, json={"cover_media_id": self.photo_a}),
            400,
            "invalid_cover_media_id",
        )
        self.add_to_project(project["id"], self.photo_a)
        self.add_to_project(project["id"], self.video)
        response = self.client.patch(
            url,
            json={
                "cover_media_id": self.video,
                "start_media_id": self.photo_a,
            },
        )
        self.assertEqual(response.status_code, 200)
        item = response.get_json()["item"]
        self.assertEqual(item["cover_media_id"], self.video)
        self.assertEqual(
            item["cover_media"],
            {
                "id": self.video,
                "type": "video",
                "file_path": "media/video.mp4",
                "thumb_path": None,
                "title": "video.mp4",
            },
        )
        self.assertEqual(item["start_media_id"], self.photo_a)
        listed = self.client.get("/api/projects").get_json()["items"][0]
        self.assertEqual(listed["cover_media"]["id"], self.video)
        self.assertEqual(listed["cover_media"]["type"], "video")
        self.assert_error(
            self.client.patch(url, json={"start_media_id": self.video}),
            400,
            "invalid_start_media_id",
        )

    def test_remove_clears_references_and_compacts_order(self) -> None:
        project = self.create_project()
        for media_id in (self.photo_a, self.video, self.photo_b):
            self.add_to_project(project["id"], media_id)
        self.client.patch(
            f"/api/projects/{project['id']}",
            json={
                "cover_media_id": self.video,
                "start_media_id": self.photo_a,
            },
        )
        removed = self.client.delete(
            f"/api/projects/{project['id']}/media/{self.photo_a}"
        )
        self.assertEqual(removed.status_code, 200)
        item = removed.get_json()["item"]
        self.assertIsNone(item["start_media_id"])
        self.assertEqual(item["cover_media_id"], self.video)
        self.assertEqual([media["sort_order"] for media in item["media"]], [0, 1])

    def test_invalid_and_unknown_media(self) -> None:
        project = self.create_project()
        self.assert_error(
            self.add_to_project(project["id"], 99999),
            404,
            "media_not_found",
        )
        self.assert_error(
            self.client.post(
                f"/api/projects/{project['id']}/media",
                json={"media_id": "1"},
            ),
            400,
            "invalid_media_id",
        )
        self.assert_error(
            self.client.patch(
                f"/api/projects/{project['id']}",
                json={"cover_media_id": 99999},
            ),
            404,
            "media_not_found",
        )

    def test_deleting_project_keeps_media_and_deleting_media_cascades_link(self) -> None:
        project = self.create_project()
        self.add_to_project(project["id"], self.photo_a)
        self.client.delete(f"/api/projects/{project['id']}")
        with panorama_app.db() as conn:
            self.assertIsNotNone(
                conn.execute(
                    "SELECT id FROM media WHERE id = ?", (self.photo_a,)
                ).fetchone()
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM project_media").fetchone()[0],
                0,
            )

        other = self.create_project("Andere Tour")
        self.add_to_project(other["id"], self.photo_b)
        self.client.patch(
            f"/api/projects/{other['id']}",
            json={
                "cover_media_id": self.photo_b,
                "start_media_id": self.photo_b,
            },
        )
        with panorama_app.db() as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (self.photo_b,))
            conn.commit()
            row = panorama_app.project_row(conn, other["id"])
            self.assertIsNone(row["cover_media_id"])
            self.assertIsNone(row["start_media_id"])
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM project_media WHERE project_id = ?",
                    (other["id"],),
                ).fetchone()[0],
                0,
            )
        listed = self.client.get("/api/projects").get_json()["items"]
        deleted_cover_project = next(
            item for item in listed if item["id"] == other["id"]
        )
        self.assertIsNone(deleted_cover_project["cover_media_id"])
        self.assertIsNone(deleted_cover_project["cover_media"])


if __name__ == "__main__":
    unittest.main()
