from __future__ import annotations

import base64
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

import app as panorama_app
from core import runtime_paths
from flask.logging import default_handler


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@contextmanager
def without_flask_console_handler():
    logger = panorama_app.app.logger
    removed = default_handler in logger.handlers
    if removed:
        logger.removeHandler(default_handler)
    try:
        yield
    finally:
        if removed:
            logger.addHandler(default_handler)


class RuntimePathTests(unittest.TestCase):
    def test_paths_follow_temporary_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.dict(
                os.environ,
                {runtime_paths.RUNTIME_ROOT_ENV: str(root)},
            ):
                paths = runtime_paths.build_runtime_paths(Path("ignored-app"))
            self.assertEqual(paths.root, root)
            self.assertEqual(paths.data, root / "data")
            self.assertEqual(paths.media, root / "media")
            self.assertEqual(paths.thumbnails, root / "media" / "thumbs")
            self.assertEqual(paths.logs, root / "logs")
            self.assertEqual(paths.database, root / "data" / "OFFLINE360_STUDIO.db")

    def test_upload_rescan_database_and_log_use_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            media = root / "media"
            log_path = root / "logs" / "offline360-studio.log"
            with patch.multiple(
                panorama_app,
                RUNTIME_ROOT=root,
                DATA_DIR=data,
                CONFIG_DIR=data / "config",
                MAPS_DIR=data / "maps",
                MEDIA_DIR=media,
                PHOTO_DIR=media / "photos",
                VIDEO_DIR=media / "videos",
                THUMB_DIR=media / "thumbs",
                DB_PATH=data / "OFFLINE360_STUDIO.db",
                LOG_DIR=root / "logs",
                LOG_PATH=log_path,
            ):
                panorama_app.app.config["TESTING"] = True
                client = panorama_app.app.test_client()
                response = client.post(
                    "/api/upload",
                    data={
                        "project": "Runtime Test",
                        "files": (io.BytesIO(PNG_1X1), "pano.png"),
                    },
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                self.assertEqual(response.get_json()["saved"], 1)
                photo = media / "photos" / "Runtime_Test" / "pano.png"
                self.assertTrue(photo.is_file())
                self.assertTrue((media / "thumbs" / "pano.jpg").is_file())
                self.assertTrue((data / "OFFLINE360_STUDIO.db").is_file())
                with closing(sqlite3.connect(data / "OFFLINE360_STUDIO.db")) as conn:
                    stored_path, thumbnail = conn.execute(
                        "SELECT file_path, thumb_path FROM media"
                    ).fetchone()
                self.assertEqual(
                    stored_path,
                    "media/photos/Runtime_Test/pano.png",
                )
                self.assertEqual(thumbnail, "media/thumbs/pano.jpg")

                second = media / "photos" / "rescan.png"
                second.write_bytes(PNG_1X1)
                response = client.post("/api/rescan")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["found"], 2)

                handler = panorama_app.configure_logging(log_path)
                try:
                    with without_flask_console_handler():
                        panorama_app.app.logger.info("runtime path test")
                    handler.flush()
                    self.assertTrue(log_path.is_file())
                    self.assertIn(
                        "runtime path test",
                        log_path.read_text(encoding="utf-8"),
                    )
                finally:
                    panorama_app.app.logger.removeHandler(handler)
                    __import__("logging").getLogger("core").removeHandler(handler)
                    handler.close()

    def test_rescan_reports_missing_media_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "missing-media"
            with patch.object(panorama_app, "MEDIA_DIR", media):
                panorama_app.app.config["TESTING"] = True
                with self.assertLogs(panorama_app.app.logger, level="ERROR") as logs:
                    response = panorama_app.app.test_client().post("/api/rescan")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.get_json()["error"]["code"],
                "media_directory_missing",
            )
            self.assertIn(
                "Rescan abgebrochen: Laufzeit-Medienordner fehlt",
                "\n".join(logs.output),
            )

    def test_upload_accepts_multiple_media_files_in_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            media = root / "media"
            with patch.multiple(
                panorama_app,
                RUNTIME_ROOT=root,
                DATA_DIR=data,
                CONFIG_DIR=data / "config",
                MAPS_DIR=data / "maps",
                MEDIA_DIR=media,
                PHOTO_DIR=media / "photos",
                VIDEO_DIR=media / "videos",
                THUMB_DIR=media / "thumbs",
                DB_PATH=data / "OFFLINE360_STUDIO.db",
                LOG_DIR=root / "logs",
                LOG_PATH=root / "logs" / "offline360-studio.log",
            ):
                panorama_app.app.config["TESTING"] = True
                response = panorama_app.app.test_client().post(
                    "/api/upload",
                    data={
                        "project": "Batch Upload",
                        "files": [
                            (io.BytesIO(PNG_1X1), "pano.png"),
                            (io.BytesIO(b"video"), "clip.mp4"),
                        ],
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            payload = response.get_json()
            self.assertEqual(payload["saved"], 2)
            self.assertEqual(payload["found"], 2)
            self.assertTrue((media / "photos" / "Batch_Upload" / "pano.png").is_file())
            self.assertTrue((media / "videos" / "Batch_Upload" / "clip.mp4").is_file())

    def test_upload_reports_runtime_directory_error_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blocked_photo_dir = root / "blocked"
            blocked_photo_dir.write_text("not a directory", encoding="utf-8")
            with patch.multiple(
                panorama_app,
                DATA_DIR=root / "data",
                CONFIG_DIR=root / "data" / "config",
                MAPS_DIR=root / "data" / "maps",
                MEDIA_DIR=root / "media",
                PHOTO_DIR=blocked_photo_dir,
                VIDEO_DIR=root / "media" / "videos",
                THUMB_DIR=root / "media" / "thumbs",
                LOG_PATH=root / "logs" / "offline360-studio.log",
            ):
                panorama_app.app.config["TESTING"] = True
                with self.assertLogs(panorama_app.app.logger, level="ERROR") as logs:
                    response = panorama_app.app.test_client().post(
                        "/api/upload",
                        data={
                            "files": (io.BytesIO(PNG_1X1), "pano.png"),
                        },
                        content_type="multipart/form-data",
                    )
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.mimetype, "application/json")
            self.assertEqual(response.get_json()["error"]["code"], "upload_failed")
            self.assertIn(
                "Upload fehlgeschlagen (gespeichert=0, Fehler=FileExistsError, errno=17)",
                "\n".join(logs.output),
            )


if __name__ == "__main__":
    unittest.main()

