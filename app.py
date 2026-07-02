from __future__ import annotations

import os
import sqlite3
import time
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"
PHOTO_DIR = MEDIA_DIR / "photos"
VIDEO_DIR = MEDIA_DIR / "videos"
THUMB_DIR = MEDIA_DIR / "thumbs"
DB_PATH = DATA_DIR / "panorama_studio.db"

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov"}

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024 * 1024  # 25 GB


def ensure_dirs() -> None:
    for path in [DATA_DIR, PHOTO_DIR, VIDEO_DIR, THUMB_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                thumb_path TEXT,
                title TEXT NOT NULL,
                project TEXT DEFAULT 'Default',
                category TEXT DEFAULT '',
                description TEXT DEFAULT '',
                favorite INTEGER DEFAULT 0,
                visible INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        ensure_column(conn, "media", "category", "TEXT DEFAULT ''")
        conn.commit()


def rel(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()


def make_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.stem


def infer_project(path: Path, media_type: str) -> str:
    root = PHOTO_DIR if media_type == "photo" else VIDEO_DIR
    try:
        relative_parent = path.parent.relative_to(root)
        if str(relative_parent) != ".":
            return relative_parent.parts[0]
    except ValueError:
        pass
    return "Default"


def create_photo_thumbnail(src: Path) -> str | None:
    try:
        thumb_name = f"{src.stem}.jpg"
        thumb_path = THUMB_DIR / thumb_name
        with Image.open(src) as image:
            image = image.convert("RGB")
            image.thumbnail((720, 405))
            canvas = Image.new("RGB", (720, 405), (22, 22, 24))
            x = (720 - image.width) // 2
            y = (405 - image.height) // 2
            canvas.paste(image, (x, y))
            canvas.save(thumb_path, "JPEG", quality=84)
        return rel(thumb_path)
    except Exception as exc:
        print(f"Thumbnail-Fehler fuer {src}: {exc}")
        return None


def scan_media() -> dict[str, Any]:
    init_db()
    found = inserted = updated = 0
    now = time.time()

    candidates: list[tuple[str, Path]] = []
    for path in PHOTO_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS:
            candidates.append(("photo", path))
    for path in VIDEO_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            candidates.append(("video", path))

    with db() as conn:
        for media_type, path in sorted(candidates, key=lambda x: str(x[1]).lower()):
            found += 1
            file_path = rel(path)
            row = conn.execute("SELECT id, project FROM media WHERE file_path = ?", (file_path,)).fetchone()
            thumb_path = create_photo_thumbnail(path) if media_type == "photo" else None
            if row:
                conn.execute(
                    "UPDATE media SET type=?, thumb_path=?, updated_at=? WHERE file_path=?",
                    (media_type, thumb_path, now, file_path),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO media
                    (type, file_path, thumb_path, title, project, category, description, favorite, visible, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, '', '', 0, 1, ?, ?)
                    """,
                    (media_type, file_path, thumb_path, make_title(path), infer_project(path, media_type), now, now),
                )
                inserted += 1
        conn.commit()

    return {"found": found, "inserted": inserted, "updated": updated}


def media_rows(include_hidden: bool = True) -> list[dict[str, Any]]:
    init_db()
    where = "" if include_hidden else "WHERE visible=1"
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT id, type, file_path, thumb_path, title, project, category, description,
                   favorite, visible, created_at, updated_at
            FROM media
            {where}
            ORDER BY project COLLATE NOCASE, favorite DESC, title COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def stats_payload() -> dict[str, Any]:
    rows = media_rows()
    visible = [r for r in rows if r.get("visible")]
    projects = sorted({r.get("project") or "Default" for r in rows}, key=str.lower)
    categories = sorted({r.get("category") for r in rows if r.get("category")}, key=str.lower)
    return {
        "total": len(rows),
        "visible": len(visible),
        "photos": sum(1 for r in visible if r["type"] == "photo"),
        "videos": sum(1 for r in visible if r["type"] == "video"),
        "favorites": sum(1 for r in visible if r.get("favorite")),
        "projects": projects,
        "categories": categories,
    }


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/media")
def api_media():
    return jsonify({"items": media_rows(), "stats": stats_payload()})


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    result = scan_media()
    return jsonify({"status": "ok", **result, "stats": stats_payload()})


@app.route("/api/media/<int:media_id>", methods=["PATCH"])
def api_update_media(media_id: int):
    payload = request.get_json(force=True) or {}
    allowed = {"title", "project", "category", "description", "favorite", "visible"}
    fields = {k: payload[k] for k in payload if k in allowed}
    if not fields:
        return jsonify({"status": "noop"})
    assignments = ", ".join(f"{k}=?" for k in fields)
    values = [int(v) if k in {"favorite", "visible"} else str(v).strip() for k, v in fields.items()]
    values.extend([time.time(), media_id])
    with db() as conn:
        conn.execute(f"UPDATE media SET {assignments}, updated_at=? WHERE id=?", values)
        conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    project = (request.form.get("project") or "Default").strip() or "Default"
    saved = 0
    for file in files:
        filename = secure_filename(file.filename or "")
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext in PHOTO_EXTENSIONS:
            target_dir = PHOTO_DIR / project
        elif ext in VIDEO_EXTENSIONS:
            target_dir = VIDEO_DIR / project
        else:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        counter = 1
        while target.exists():
            target = target_dir / f"{Path(filename).stem}_{counter}{ext}"
            counter += 1
        file.save(target)
        saved += 1
    result = scan_media()
    return jsonify({"status": "ok", "saved": saved, **result, "stats": stats_payload()})


@app.route("/media/<path:filename>")
def serve_media(filename: str):
    return send_from_directory(MEDIA_DIR, filename)


@app.route("/thumbs/<path:filename>")
def serve_thumb(filename: str):
    return send_from_directory(THUMB_DIR, filename)


if __name__ == "__main__":
    init_db()
    url = "http://127.0.0.1:5000"
    print(f"Panorama Studio laeuft: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host="127.0.0.1", port=5000, debug=False)
