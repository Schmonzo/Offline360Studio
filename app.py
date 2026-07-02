from __future__ import annotations

import math
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
MIN_START_FOV = math.radians(25)
MAX_START_FOV = math.radians(165)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024 * 1024  # 25 GB


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def ensure_dirs() -> None:
    for path in [DATA_DIR, PHOTO_DIR, VIDEO_DIR, THUMB_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, factory=DatabaseConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
                start_yaw REAL NULL,
                start_pitch REAL NULL,
                start_fov REAL NULL,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        ensure_column(conn, "media", "category", "TEXT DEFAULT ''")
        ensure_column(conn, "media", "start_yaw", "REAL NULL")
        ensure_column(conn, "media", "start_pitch", "REAL NULL")
        ensure_column(conn, "media", "start_fov", "REAL NULL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                cover_media_id INTEGER NULL,
                start_media_id INTEGER NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (cover_media_id) REFERENCES media(id) ON DELETE SET NULL,
                FOREIGN KEY (start_media_id) REFERENCES media(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_media (
                project_id INTEGER NOT NULL,
                media_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (project_id, media_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_project_media_project_sort
            ON project_media(project_id, sort_order)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hotspots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_media_id INTEGER NOT NULL,
                action_type TEXT NOT NULL CHECK (action_type IN ('panorama', 'info')),
                yaw REAL NOT NULL,
                pitch REAL NOT NULL,
                title TEXT DEFAULT '',
                info_text TEXT DEFAULT '',
                target_media_id INTEGER,
                visible INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (source_media_id) REFERENCES media(id) ON DELETE CASCADE,
                FOREIGN KEY (target_media_id) REFERENCES media(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hotspots_source_media_id ON hotspots(source_media_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hotspots_target_media_id ON hotspots(target_media_id)"
        )
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
                   favorite, visible, start_yaw, start_pitch, start_fov,
                   created_at, updated_at
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


def api_error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def media_row(conn: sqlite3.Connection, media_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, type FROM media WHERE id = ?",
        (media_id,),
    ).fetchone()


PROJECT_FIELDS = {"name", "description", "cover_media_id", "start_media_id"}


def project_row(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, name, description, cover_media_id, start_media_id,
               created_at, updated_at
        FROM projects
        WHERE id = ?
        """,
        (project_id,),
    ).fetchone()


def project_payload(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    include_media: bool = True,
) -> dict[str, Any]:
    result = dict(row)
    if include_media:
        media = conn.execute(
            """
            SELECT m.id, m.type, m.file_path, m.thumb_path, m.title, m.project,
                   m.category, m.description, m.favorite, m.visible,
                   m.start_yaw, m.start_pitch, m.start_fov,
                   m.created_at, m.updated_at, pm.sort_order
            FROM project_media pm
            JOIN media m ON m.id = pm.media_id
            WHERE pm.project_id = ?
            ORDER BY pm.sort_order, pm.media_id
            """,
            (row["id"],),
        ).fetchall()
        result["media"] = [dict(item) for item in media]
        result["media_count"] = len(media)
    else:
        result["media_count"] = conn.execute(
            "SELECT COUNT(*) FROM project_media WHERE project_id = ?",
            (row["id"],),
        ).fetchone()[0]
    return result


def parse_project_data(
    conn: sqlite3.Connection,
    payload: Any,
    existing: sqlite3.Row | None = None,
):
    if not isinstance(payload, dict):
        return None, api_error(
            "invalid_json",
            "Der Request-Body muss ein JSON-Objekt sein.",
            400,
        )
    unknown = set(payload) - PROJECT_FIELDS
    if unknown:
        return None, api_error(
            "invalid_field",
            "Unbekannte Projekt-Felder: " + ", ".join(sorted(unknown)),
            400,
        )
    if existing is not None and not payload:
        return None, api_error(
            "empty_update",
            "Mindestens ein Projekt-Feld muss angegeben werden.",
            400,
        )

    merged = dict(existing) if existing is not None else {
        "name": None,
        "description": "",
        "cover_media_id": None,
        "start_media_id": None,
    }
    merged.update(payload)
    if not isinstance(merged["name"], str) or not merged["name"].strip():
        return None, api_error(
            "invalid_name",
            "Der Projektname ist erforderlich.",
            400,
        )
    if not isinstance(merged["description"], str):
        return None, api_error(
            "invalid_description",
            "Die Beschreibung muss eine Zeichenkette sein.",
            400,
        )

    project_id = existing["id"] if existing is not None else None
    for field in ("cover_media_id", "start_media_id"):
        media_id = merged[field]
        if media_id is None:
            continue
        if isinstance(media_id, bool) or not isinstance(media_id, int):
            return None, api_error(
                f"invalid_{field}",
                f"{field} muss eine Medien-ID oder null sein.",
                400,
            )
        media = media_row(conn, media_id)
        if media is None:
            return None, api_error(
                "media_not_found",
                "Das Medium wurde nicht gefunden.",
                404,
            )
        assigned = project_id is not None and conn.execute(
            """
            SELECT 1 FROM project_media
            WHERE project_id = ? AND media_id = ?
            """,
            (project_id, media_id),
        ).fetchone()
        if not assigned:
            return None, api_error(
                f"invalid_{field}",
                f"{field} muss dem Projekt zugeordnet sein.",
                400,
            )
        if field == "start_media_id" and media["type"] != "photo":
            return None, api_error(
                "invalid_start_media_id",
                "Das Startpanorama muss ein Foto sein.",
                400,
            )

    return {
        "name": merged["name"].strip(),
        "description": merged["description"].strip(),
        "cover_media_id": merged["cover_media_id"],
        "start_media_id": merged["start_media_id"],
    }, None


def validate_source_media(conn: sqlite3.Connection, media_id: int):
    row = media_row(conn, media_id)
    if row is None:
        return api_error("media_not_found", "Das Quellmedium wurde nicht gefunden.", 404)
    if row["type"] != "photo":
        return api_error(
            "invalid_source_media",
            "Hotspots können nur für Fotos angelegt werden.",
            400,
        )
    return None


def validate_hotspot_data(
    conn: sqlite3.Connection,
    data: dict[str, Any],
) -> tuple[dict[str, Any] | None, Any | None]:
    action_type = data.get("action_type")
    if action_type not in {"panorama", "info"}:
        return None, api_error(
            "invalid_action_type",
            "action_type muss 'panorama' oder 'info' sein.",
            400,
        )

    coordinates: dict[str, float] = {}
    for field in ("yaw", "pitch"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, api_error(
                "invalid_coordinates",
                "yaw und pitch müssen endliche Zahlen sein.",
                400,
            )
        value = float(value)
        if not math.isfinite(value):
            return None, api_error(
                "invalid_coordinates",
                "yaw und pitch müssen endliche Zahlen sein.",
                400,
            )
        coordinates[field] = value

    if not -math.pi / 2 <= coordinates["pitch"] <= math.pi / 2:
        return None, api_error(
            "invalid_pitch",
            "pitch muss zwischen -π/2 und π/2 liegen.",
            400,
        )

    target_media_id = data.get("target_media_id")
    if action_type == "panorama":
        if (
            isinstance(target_media_id, bool)
            or not isinstance(target_media_id, int)
        ):
            return None, api_error(
                "invalid_target_media",
                "Ein Panorama-Hotspot benötigt target_media_id.",
                400,
            )
        target = media_row(conn, target_media_id)
        if target is None:
            return None, api_error(
                "target_media_not_found",
                "Das Zielmedium wurde nicht gefunden.",
                404,
            )
        if target["type"] != "photo":
            return None, api_error(
                "invalid_target_media",
                "Das Zielmedium eines Panorama-Hotspots muss ein Foto sein.",
                400,
            )
    elif target_media_id is not None:
        return None, api_error(
            "invalid_target_media",
            "Ein Info-Hotspot darf kein target_media_id besitzen.",
            400,
        )

    for field in ("title", "info_text"):
        value = data.get(field, "")
        if not isinstance(value, str):
            return None, api_error(
                "invalid_field",
                f"{field} muss eine Zeichenkette sein.",
                400,
            )

    visible = data.get("visible", 1)
    if isinstance(visible, bool):
        visible = int(visible)
    if visible not in {0, 1}:
        return None, api_error(
            "invalid_visible",
            "visible muss 0, 1, false oder true sein.",
            400,
        )

    return {
        "action_type": action_type,
        "yaw": coordinates["yaw"],
        "pitch": coordinates["pitch"],
        "title": data.get("title", "").strip(),
        "info_text": data.get("info_text", "").strip(),
        "target_media_id": target_media_id,
        "visible": int(visible),
    }, None


def hotspot_payload(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def validate_start_view(data: dict[str, Any]):
    allowed = {"yaw", "pitch", "fov"}
    unknown_fields = set(data) - allowed
    if unknown_fields:
        return None, api_error(
            "invalid_field",
            "Unbekannte Startansicht-Felder: " + ", ".join(sorted(unknown_fields)),
            400,
        )
    if set(data) != allowed:
        return None, api_error(
            "invalid_start_view",
            "yaw, pitch und fov müssen vollständig angegeben werden.",
            400,
        )

    values: dict[str, float] = {}
    for field in ("yaw", "pitch", "fov"):
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, api_error(
                "invalid_start_view",
                "yaw, pitch und fov müssen endliche Zahlen sein.",
                400,
            )
        value = float(value)
        if not math.isfinite(value):
            return None, api_error(
                "invalid_start_view",
                "yaw, pitch und fov müssen endliche Zahlen sein.",
                400,
            )
        values[field] = value

    if not -math.pi / 2 <= values["pitch"] <= math.pi / 2:
        return None, api_error(
            "invalid_pitch",
            "pitch muss zwischen -π/2 und π/2 liegen.",
            400,
        )
    if not MIN_START_FOV <= values["fov"] <= MAX_START_FOV:
        return None, api_error(
            "invalid_fov",
            "fov muss zwischen 25° und 165° liegen.",
            400,
        )
    return values, None


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/media")
def api_media():
    return jsonify({"items": media_rows(), "stats": stats_payload()})


@app.route("/api/projects", methods=["GET", "POST"])
def api_projects():
    init_db()
    if request.method == "GET":
        with db() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, cover_media_id, start_media_id,
                       created_at, updated_at
                FROM projects
                ORDER BY created_at, id
                """
            ).fetchall()
            items = [project_payload(conn, row, include_media=False) for row in rows]
        return jsonify({"items": items})

    payload = request.get_json(silent=True)
    with db() as conn:
        data, validation_error = parse_project_data(conn, payload)
        if validation_error:
            return validation_error
        now = time.time()
        cursor = conn.execute(
            """
            INSERT INTO projects
            (name, description, cover_media_id, start_media_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data["description"],
                data["cover_media_id"],
                data["start_media_id"],
                now,
                now,
            ),
        )
        row = project_row(conn, int(cursor.lastrowid))
        result = project_payload(conn, row)
        conn.commit()
    return jsonify({"item": result}), 201


@app.route("/api/projects/<int:project_id>", methods=["GET", "PATCH", "DELETE"])
def api_project(project_id: int):
    init_db()
    with db() as conn:
        row = project_row(conn, project_id)
        if row is None:
            return api_error(
                "project_not_found",
                "Das Projekt wurde nicht gefunden.",
                404,
            )

        if request.method == "GET":
            return jsonify({"item": project_payload(conn, row)})

        if request.method == "DELETE":
            result = project_payload(conn, row, include_media=False)
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return jsonify({"status": "ok", "item": result})

        payload = request.get_json(silent=True)
        data, validation_error = parse_project_data(conn, payload, row)
        if validation_error:
            return validation_error
        conn.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, cover_media_id = ?,
                start_media_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["name"],
                data["description"],
                data["cover_media_id"],
                data["start_media_id"],
                time.time(),
                project_id,
            ),
        )
        updated = project_row(conn, project_id)
        result = project_payload(conn, updated)
        conn.commit()
    return jsonify({"item": result})


@app.route("/api/projects/<int:project_id>/media", methods=["POST"])
def api_add_project_media(project_id: int):
    init_db()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error(
            "invalid_json",
            "Der Request-Body muss ein JSON-Objekt sein.",
            400,
        )
    if set(payload) != {"media_id"}:
        return api_error(
            "invalid_field",
            "Der Request-Body muss genau media_id enthalten.",
            400,
        )
    media_id = payload["media_id"]
    if isinstance(media_id, bool) or not isinstance(media_id, int):
        return api_error(
            "invalid_media_id",
            "media_id muss eine Ganzzahl sein.",
            400,
        )

    with db() as conn:
        project = project_row(conn, project_id)
        if project is None:
            return api_error(
                "project_not_found",
                "Das Projekt wurde nicht gefunden.",
                404,
            )
        if media_row(conn, media_id) is None:
            return api_error(
                "media_not_found",
                "Das Medium wurde nicht gefunden.",
                404,
            )
        if conn.execute(
            """
            SELECT 1 FROM project_media
            WHERE project_id = ? AND media_id = ?
            """,
            (project_id, media_id),
        ).fetchone():
            return api_error(
                "media_already_assigned",
                "Das Medium ist dem Projekt bereits zugeordnet.",
                400,
            )
        next_order = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1
            FROM project_media
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO project_media(project_id, media_id, sort_order)
            VALUES (?, ?, ?)
            """,
            (project_id, media_id, next_order),
        )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (time.time(), project_id),
        )
        updated = project_row(conn, project_id)
        result = project_payload(conn, updated)
        conn.commit()
    return jsonify({"item": result}), 201


@app.route(
    "/api/projects/<int:project_id>/media/<int:media_id>",
    methods=["DELETE"],
)
def api_remove_project_media(project_id: int, media_id: int):
    init_db()
    with db() as conn:
        project = project_row(conn, project_id)
        if project is None:
            return api_error(
                "project_not_found",
                "Das Projekt wurde nicht gefunden.",
                404,
            )
        if media_row(conn, media_id) is None:
            return api_error(
                "media_not_found",
                "Das Medium wurde nicht gefunden.",
                404,
            )
        assignment = conn.execute(
            """
            SELECT 1 FROM project_media
            WHERE project_id = ? AND media_id = ?
            """,
            (project_id, media_id),
        ).fetchone()
        if assignment is None:
            return api_error(
                "media_not_assigned",
                "Das Medium ist dem Projekt nicht zugeordnet.",
                400,
            )
        conn.execute(
            "DELETE FROM project_media WHERE project_id = ? AND media_id = ?",
            (project_id, media_id),
        )
        conn.execute(
            """
            UPDATE projects
            SET cover_media_id = CASE WHEN cover_media_id = ? THEN NULL ELSE cover_media_id END,
                start_media_id = CASE WHEN start_media_id = ? THEN NULL ELSE start_media_id END,
                updated_at = ?
            WHERE id = ?
            """,
            (media_id, media_id, time.time(), project_id),
        )
        remaining = conn.execute(
            """
            SELECT media_id FROM project_media
            WHERE project_id = ?
            ORDER BY sort_order, media_id
            """,
            (project_id,),
        ).fetchall()
        for sort_order, item in enumerate(remaining):
            conn.execute(
                """
                UPDATE project_media SET sort_order = ?
                WHERE project_id = ? AND media_id = ?
                """,
                (sort_order, project_id, item["media_id"]),
            )
        updated = project_row(conn, project_id)
        result = project_payload(conn, updated)
        conn.commit()
    return jsonify({"item": result})


@app.route("/api/projects/<int:project_id>/media/order", methods=["PATCH"])
def api_order_project_media(project_id: int):
    init_db()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"media_ids"}:
        return api_error(
            "invalid_order",
            "Der Request-Body muss genau media_ids enthalten.",
            400,
        )
    media_ids = payload["media_ids"]
    if (
        not isinstance(media_ids, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in media_ids)
        or len(media_ids) != len(set(media_ids))
    ):
        return api_error(
            "invalid_order",
            "media_ids muss eine Liste eindeutiger Ganzzahlen sein.",
            400,
        )

    with db() as conn:
        project = project_row(conn, project_id)
        if project is None:
            return api_error(
                "project_not_found",
                "Das Projekt wurde nicht gefunden.",
                404,
            )
        if any(media_row(conn, media_id) is None for media_id in media_ids):
            return api_error(
                "media_not_found",
                "Mindestens ein Medium wurde nicht gefunden.",
                404,
            )
        assigned_ids = [
            row["media_id"]
            for row in conn.execute(
                """
                SELECT media_id FROM project_media
                WHERE project_id = ?
                ORDER BY sort_order, media_id
                """,
                (project_id,),
            ).fetchall()
        ]
        if len(media_ids) != len(assigned_ids) or set(media_ids) != set(assigned_ids):
            return api_error(
                "invalid_order",
                "media_ids muss alle zugeordneten Medien genau einmal enthalten.",
                400,
            )
        for sort_order, media_id in enumerate(media_ids):
            conn.execute(
                """
                UPDATE project_media SET sort_order = ?
                WHERE project_id = ? AND media_id = ?
                """,
                (sort_order, project_id, media_id),
            )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (time.time(), project_id),
        )
        updated = project_row(conn, project_id)
        result = project_payload(conn, updated)
        conn.commit()
    return jsonify({"item": result})


@app.route("/api/media/<int:media_id>/start-view", methods=["PUT", "DELETE"])
def api_media_start_view(media_id: int):
    with db() as conn:
        media = media_row(conn, media_id)
        if media is None:
            return api_error("media_not_found", "Das Medium wurde nicht gefunden.", 404)
        if media["type"] != "photo":
            return api_error(
                "invalid_media_type",
                "Eine Startansicht kann nur für Foto-Medien gespeichert werden.",
                400,
            )

        if request.method == "DELETE":
            values = {"yaw": None, "pitch": None, "fov": None}
        else:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return api_error(
                    "invalid_json",
                    "Der Request-Body muss ein JSON-Objekt sein.",
                    400,
                )
            values, validation_error = validate_start_view(payload)
            if validation_error:
                return validation_error

        conn.execute(
            """
            UPDATE media
            SET start_yaw = ?, start_pitch = ?, start_fov = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["yaw"],
                values["pitch"],
                values["fov"],
                time.time(),
                media_id,
            ),
        )
        conn.commit()

    return jsonify(
        {
            "status": "ok",
            "item": {
                "id": media_id,
                "start_yaw": values["yaw"],
                "start_pitch": values["pitch"],
                "start_fov": values["fov"],
            },
        }
    )


@app.route("/api/media/<int:media_id>/hotspots")
def api_media_hotspots(media_id: int):
    with db() as conn:
        source_error = validate_source_media(conn, media_id)
        if source_error:
            return source_error
        rows = conn.execute(
            """
            SELECT id, source_media_id, action_type, yaw, pitch, title, info_text,
                   target_media_id, visible, created_at, updated_at
            FROM hotspots
            WHERE source_media_id = ?
            ORDER BY id
            """,
            (media_id,),
        ).fetchall()
    return jsonify({"items": [hotspot_payload(row) for row in rows]})


@app.route("/api/media/<int:media_id>/hotspots", methods=["POST"])
def api_create_hotspot(media_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error(
            "invalid_json",
            "Der Request-Body muss ein JSON-Objekt sein.",
            400,
        )

    with db() as conn:
        source_error = validate_source_media(conn, media_id)
        if source_error:
            return source_error
        data, validation_error = validate_hotspot_data(conn, payload)
        if validation_error:
            return validation_error

        now = time.time()
        cursor = conn.execute(
            """
            INSERT INTO hotspots
            (source_media_id, action_type, yaw, pitch, title, info_text,
             target_media_id, visible, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                data["action_type"],
                data["yaw"],
                data["pitch"],
                data["title"],
                data["info_text"],
                data["target_media_id"],
                data["visible"],
                now,
                now,
            ),
        )
        hotspot_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, source_media_id, action_type, yaw, pitch, title, info_text,
                   target_media_id, visible, created_at, updated_at
            FROM hotspots
            WHERE id = ?
            """,
            (hotspot_id,),
        ).fetchone()
        conn.commit()
    return jsonify({"item": hotspot_payload(row)}), 201


@app.route("/api/hotspots/<int:hotspot_id>", methods=["PATCH"])
def api_update_hotspot(hotspot_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error(
            "invalid_json",
            "Der Request-Body muss ein JSON-Objekt sein.",
            400,
        )

    allowed = {
        "action_type",
        "yaw",
        "pitch",
        "title",
        "info_text",
        "target_media_id",
        "visible",
    }
    unknown_fields = set(payload) - allowed
    if unknown_fields:
        return api_error(
            "invalid_field",
            "Unbekannte Hotspot-Felder: " + ", ".join(sorted(unknown_fields)),
            400,
        )
    if not payload:
        return api_error(
            "empty_update",
            "Mindestens ein Hotspot-Feld muss angegeben werden.",
            400,
        )

    with db() as conn:
        row = conn.execute(
            """
            SELECT id, source_media_id, action_type, yaw, pitch, title, info_text,
                   target_media_id, visible, created_at, updated_at
            FROM hotspots
            WHERE id = ?
            """,
            (hotspot_id,),
        ).fetchone()
        if row is None:
            return api_error(
                "hotspot_not_found",
                "Der Hotspot wurde nicht gefunden.",
                404,
            )

        source_error = validate_source_media(conn, row["source_media_id"])
        if source_error:
            return source_error
        merged = dict(row)
        merged.update(payload)
        data, validation_error = validate_hotspot_data(conn, merged)
        if validation_error:
            return validation_error

        now = time.time()
        conn.execute(
            """
            UPDATE hotspots
            SET action_type = ?, yaw = ?, pitch = ?, title = ?, info_text = ?,
                target_media_id = ?, visible = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["action_type"],
                data["yaw"],
                data["pitch"],
                data["title"],
                data["info_text"],
                data["target_media_id"],
                data["visible"],
                now,
                hotspot_id,
            ),
        )
        updated = conn.execute(
            """
            SELECT id, source_media_id, action_type, yaw, pitch, title, info_text,
                   target_media_id, visible, created_at, updated_at
            FROM hotspots
            WHERE id = ?
            """,
            (hotspot_id,),
        ).fetchone()
        conn.commit()
    return jsonify({"item": hotspot_payload(updated)})


@app.route("/api/hotspots/<int:hotspot_id>", methods=["DELETE"])
def api_delete_hotspot(hotspot_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM hotspots WHERE id = ?",
            (hotspot_id,),
        ).fetchone()
        if row is None:
            return api_error(
                "hotspot_not_found",
                "Der Hotspot wurde nicht gefunden.",
                404,
            )
        conn.execute("DELETE FROM hotspots WHERE id = ?", (hotspot_id,))
        conn.commit()
    return jsonify({"status": "ok", "id": hotspot_id})


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
