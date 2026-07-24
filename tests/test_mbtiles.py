from __future__ import annotations

import gzip
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as panorama_app


PBF_TILE = b"\x1a\x0b\x0a\x04test\x28\x80\x20\x78\x02"


def mbtiles_bytes(
    tile_format: str = "png",
    *,
    metadata_table: bool = True,
    tiles_table: bool = True,
    tiles_view: bool = False,
    normalized: bool = False,
    map_table: bool = True,
    images_table: bool = True,
    invalid_tile_reference: bool = False,
    tile_data: bytes = b"tile",
    metadata_json: object | str | None = None,
) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source.mbtiles"
        with closing(sqlite3.connect(path)) as conn:
            if metadata_table:
                conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
                metadata = [
                        ("name", "Alpenkarte"),
                        ("format", tile_format),
                        ("type", "baselayer"),
                        ("minzoom", "2"),
                        ("maxzoom", "2"),
                        ("bounds", "5,45,11,48"),
                        ("center", "8,46.5,7"),
                        ("attribution", "Lokale Testdaten"),
                    ]
                if metadata_json is not None:
                    metadata.append(
                        (
                            "json",
                            metadata_json
                            if isinstance(metadata_json, str)
                            else json.dumps(metadata_json),
                        )
                    )
                conn.executemany("INSERT INTO metadata VALUES (?, ?)", metadata)
            if normalized:
                if map_table:
                    conn.execute(
                        """
                        CREATE TABLE map (
                            zoom_level INTEGER,
                            tile_column INTEGER,
                            tile_row INTEGER,
                            tile_id TEXT
                        )
                        """
                    )
                    tile_id = "missing" if invalid_tile_reference else "tile-1"
                    conn.execute("INSERT INTO map VALUES (2, 1, 2, ?)", (tile_id,))
                if images_table:
                    conn.execute(
                        "CREATE TABLE images (tile_id TEXT, tile_data BLOB)"
                    )
                    conn.execute(
                        "INSERT INTO images VALUES ('tile-1', ?)", (tile_data,)
                    )
            elif tiles_table and tiles_view:
                conn.execute(
                    """
                    CREATE TABLE tile_rows (
                        zoom_level INTEGER,
                        tile_column INTEGER,
                        tile_row INTEGER,
                        tile_data BLOB
                    )
                    """
                )
                conn.execute("INSERT INTO tile_rows VALUES (2, 1, 2, ?)", (tile_data,))
                conn.execute(
                    """
                    CREATE VIEW tiles AS
                    SELECT zoom_level, tile_column, tile_row, tile_data
                    FROM tile_rows
                    """
                )
            elif tiles_table:
                conn.execute(
                    """
                    CREATE TABLE tiles (
                        zoom_level INTEGER,
                        tile_column INTEGER,
                        tile_row INTEGER,
                        tile_data BLOB
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO tiles VALUES (2, 1, 2, ?)", (tile_data,)
                )
            conn.commit()
        return path.read_bytes()


class MBTilesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        data = root / "data"
        media = root / "media"
        self.path_patch = patch.multiple(
            panorama_app,
            DATA_DIR=data,
            CONFIG_DIR=data / "config",
            MAPS_DIR=data / "maps",
            MEDIA_DIR=media,
            PHOTO_DIR=media / "photos",
            VIDEO_DIR=media / "videos",
            THUMB_DIR=media / "thumbs",
            DB_PATH=data / "OFFLINE360_STUDIO.db",
        )
        self.path_patch.start()
        panorama_app.app.config.update(TESTING=True)
        panorama_app.init_db()
        self.client = panorama_app.app.test_client()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def import_map(self, content: bytes, filename: str = "original.mbtiles"):
        return self.client.post(
            "/api/maps/sources/import",
            data={"file": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    def assert_error(self, response, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["error"]["code"], code)

    def test_valid_import_lists_source_and_uses_server_filename(self) -> None:
        response = self.import_map(mbtiles_bytes())
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        item = response.get_json()["item"]
        self.assertEqual(item["name"], "Alpenkarte")
        self.assertEqual(item["format"], "png")
        self.assertEqual(item["source_id"], item["id"])
        self.assertEqual(item["map_type"], "raster")
        self.assertNotIn("type", item)
        self.assertEqual(item["schema_type"], "flat")
        self.assertEqual((item["min_zoom"], item["max_zoom"]), (2, 2))
        self.assertEqual(item["bounds"], "5,45,11,48")
        self.assertEqual(item["center"], "8,46.5,7")
        self.assertEqual(item["attribution"], "Lokale Testdaten")
        self.assertEqual(item["vector_layers"], [])
        self.assertFalse(item["style_available"])
        self.assertFalse(item["active"])
        self.assertNotEqual(item["filename"], "original.mbtiles")
        self.assertTrue((panorama_app.MAPS_DIR / item["filename"]).is_file())
        listed = self.client.get("/api/maps/sources").get_json()["items"]
        self.assertEqual([source["id"] for source in listed], [item["id"]])

    def test_tiles_view_is_accepted_as_flat_schema(self) -> None:
        response = self.import_map(mbtiles_bytes(tiles_view=True))
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["item"]["schema_type"], "flat")

    def test_normalized_schema_is_imported_and_exposed(self) -> None:
        response = self.import_map(mbtiles_bytes(normalized=True))
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        item = response.get_json()["item"]
        self.assertEqual(item["schema_type"], "normalized")
        with panorama_app.db() as conn:
            schema_type = conn.execute(
                "SELECT schema_type FROM map_sources WHERE id = ?", (item["id"],)
            ).fetchone()[0]
        self.assertEqual(schema_type, "normalized")

    def test_schema_type_migration_is_idempotent(self) -> None:
        with panorama_app.db() as conn:
            conn.execute("DROP TABLE map_sources")
            conn.execute(
                """
                CREATE TABLE map_sources (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    filename TEXT NOT NULL UNIQUE,
                    format TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    imported_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO map_sources
                (name, filename, format, active, imported_at)
                VALUES ('Altbestand', '0123456789abcdef0123456789abcdef.mbtiles',
                        'png', 0, 1)
                """
            )
            conn.execute("DELETE FROM schema_migrations WHERE version >= 2")
            conn.commit()
        panorama_app.init_db()
        panorama_app.init_db()
        with panorama_app.db() as conn:
            row = conn.execute(
                """
                SELECT schema_type, map_type, center, vector_layers
                FROM map_sources WHERE name = 'Altbestand'
                """
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE map_sources SET schema_type = 'invalid' "
                    "WHERE name = 'Altbestand'"
                )
        self.assertEqual(tuple(row), ("flat", "raster", None, "[]"))

    def test_invalid_sqlite_and_missing_tables_are_rejected(self) -> None:
        self.assert_error(self.import_map(b"not sqlite"), 400, "invalid_mbtiles")
        self.assert_error(
            self.import_map(mbtiles_bytes(metadata_table=False)),
            400,
            "metadata_table_missing",
        )
        self.assert_error(
            self.import_map(mbtiles_bytes(tiles_table=False)),
            400,
            "tiles_table_missing",
        )

    def test_incomplete_normalized_schemas_are_rejected(self) -> None:
        for options in (
            {"map_table": False},
            {"images_table": False},
        ):
            with self.subTest(options=options):
                response = self.import_map(
                    mbtiles_bytes(normalized=True, **options)
                )
                self.assert_error(response, 400, "tiles_table_missing")
                self.assertEqual(
                    response.get_json()["error"]["message"],
                    "Weder ein gÃ¼ltiges tiles-Schema noch ein gÃ¼ltiges "
                    "map/images-Schema gefunden.",
                )

    def test_normalized_schema_rejects_missing_image_reference(self) -> None:
        self.assert_error(
            self.import_map(
                mbtiles_bytes(normalized=True, invalid_tile_reference=True)
            ),
            400,
            "tile_references_invalid",
        )

    def test_vector_flat_and_normalized_are_imported(self) -> None:
        vector_metadata = {
            "vector_layers": [
                {
                    "id": "transport",
                    "description": "Lokale Wege",
                    "fields": {"class": "String"},
                    "minzoom": 2,
                    "maxzoom": 14,
                }
            ]
        }
        for normalized in (False, True):
            with self.subTest(normalized=normalized):
                response = self.import_map(
                    mbtiles_bytes(
                        "pbf",
                        normalized=normalized,
                        tile_data=PBF_TILE,
                        metadata_json=vector_metadata,
                    ),
                    f"vector-{normalized}.mbtiles",
                )
                self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
                item = response.get_json()["item"]
                self.assertEqual(item["map_type"], "vector")
                self.assertEqual(
                    item["schema_type"], "normalized" if normalized else "flat"
                )
                self.assertEqual(item["vector_layers"][0]["id"], "transport")
                self.assertTrue(item["style_available"])

    def test_raster_formats_are_still_allowed(self) -> None:
        for tile_format in ("png", "jpg", "jpeg", "webp"):
            with self.subTest(tile_format=tile_format):
                response = self.import_map(
                    mbtiles_bytes(tile_format),
                    f"source-{tile_format}.mbtiles",
                )
                self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

    def test_map_type_is_derived_and_validated_centrally(self) -> None:
        for tile_format, expected in (
            ("png", "raster"),
            ("jpg", "raster"),
            ("pbf", "vector"),
            ("mvt", "vector"),
        ):
            with self.subTest(tile_format=tile_format):
                self.assertEqual(
                    panorama_app.mbtiles.map_type_for_format(tile_format),
                    expected,
                )
                self.assertEqual(
                    panorama_app.mbtiles.validated_map_type(expected, tile_format),
                    expected,
                )
        self.assertEqual(
            panorama_app.mbtiles.validated_map_type("vector", "png"),
            "unknown",
        )
        self.assertEqual(
            panorama_app.mbtiles.validated_map_type("other", "pbf"),
            "unknown",
        )

    def test_vector_tile_content_type_and_gzip_encoding(self) -> None:
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                tile = gzip.compress(PBF_TILE) if compressed else PBF_TILE
                item = self.import_map(
                    mbtiles_bytes("pbf", tile_data=tile),
                    f"vector-{compressed}.mbtiles",
                ).get_json()["item"]
                response = self.client.get(
                    f"/api/maps/tiles/{item['id']}/2/1/1"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.content_type, "application/vnd.mapbox-vector-tile"
                )
                self.assertEqual(response.data, tile)
                if compressed:
                    self.assertEqual(response.headers["Content-Encoding"], "gzip")
                    self.assertTrue(response.data.startswith(b"\x1f\x8b"))
                else:
                    self.assertNotIn("Content-Encoding", response.headers)

    def test_vector_metadata_and_generated_style_are_offline(self) -> None:
        item = self.import_map(
            mbtiles_bytes(
                "mvt",
                tile_data=PBF_TILE,
                metadata_json={
                    "vector_layers": [
                        {"id": "land", "fields": {"kind": "String"}},
                        {"id": "roads", "fields": {}},
                    ],
                    "tiles": ["https://example.invalid/{z}/{x}/{y}.pbf"],
                    "glyphs": "https://example.invalid/fonts/{fontstack}/{range}.pbf",
                },
            )
        ).get_json()["item"]
        self.assertEqual(item["format"], "mvt")
        self.assertEqual([layer["id"] for layer in item["vector_layers"]], ["land", "roads"])
        response = self.client.get(f"/api/maps/sources/{item['id']}/style.json")
        self.assertEqual(response.status_code, 200)
        style = response.get_json()
        serialized = json.dumps(style)
        self.assertNotIn("http://", serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("glyphs", style)
        self.assertNotIn("sprite", style)
        self.assertEqual(
            style["sources"]["offline-tiles"]["tiles"],
            [f"/api/maps/tiles/{item['id']}/{{z}}/{{x}}/{{y}}"],
        )
        tile_url = style["sources"]["offline-tiles"]["tiles"][0]
        self.assertTrue(tile_url.startswith("/api/maps/tiles/"))
        self.assertTrue(tile_url.endswith("/{z}/{x}/{y}"))
        self.assertEqual(style["center"], [8.0, 46.5])
        self.assertEqual(style["zoom"], 7.0)
        self.assertEqual(len(style["layers"]), 7)
        self.assertEqual(
            {layer["type"] for layer in style["layers"]},
            {"background", "fill", "line", "circle"},
        )

    def test_invalid_metadata_json_is_ignored_defensively(self) -> None:
        response = self.import_map(
            mbtiles_bytes("pbf", tile_data=PBF_TILE, metadata_json="{broken")
        )
        self.assertEqual(response.status_code, 201)
        item = response.get_json()["item"]
        self.assertEqual(item["vector_layers"], [])
        self.assertFalse(item["style_available"])
        style = self.client.get(
            f"/api/maps/sources/{item['id']}/style.json"
        ).get_json()
        self.assertEqual([layer["type"] for layer in style["layers"]], ["background"])

    def test_activate_only_one_rename_and_delete_file(self) -> None:
        first = self.import_map(mbtiles_bytes(), "first.mbtiles").get_json()["item"]
        second = self.import_map(mbtiles_bytes(), "second.mbtiles").get_json()["item"]
        response = self.client.patch(
            f"/api/maps/sources/{first['id']}", json={"active": True}
        )
        self.assertTrue(response.get_json()["item"]["active"])
        self.client.patch(
            f"/api/maps/sources/{second['id']}",
            json={"active": True, "name": "Neue Karte"},
        )
        sources = self.client.get("/api/maps/sources").get_json()["items"]
        active = [source for source in sources if source["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], second["id"])
        self.assertEqual(active[0]["name"], "Neue Karte")
        path = panorama_app.MAPS_DIR / second["filename"]
        response = self.client.delete(f"/api/maps/sources/{second['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(path.exists())
        self.assertIsNone(self.client.get("/api/maps/active").get_json()["item"])

    def test_active_endpoint_selects_source_and_null_deactivates_all(self) -> None:
        raster = self.import_map(
            mbtiles_bytes(), "raster.mbtiles"
        ).get_json()["item"]
        vector = self.import_map(
            mbtiles_bytes(
                "pbf",
                tile_data=PBF_TILE,
                metadata_json={"vector_layers": [{"id": "test", "fields": {}}]},
            ),
            "vector.mbtiles",
        ).get_json()["item"]

        response = self.client.patch(
            "/api/maps/active", json={"source_id": raster["id"]}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["item"]["id"], raster["id"])

        response = self.client.patch(
            "/api/maps/active", json={"source_id": vector["id"]}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["item"]["id"], vector["id"])
        sources = self.client.get("/api/maps/sources").get_json()["items"]
        self.assertEqual(
            [source["id"] for source in sources if source["active"]],
            [vector["id"]],
        )

        response = self.client.patch("/api/maps/active", json={"source_id": None})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(response.get_json()["item"])
        sources = self.client.get("/api/maps/sources").get_json()["items"]
        self.assertFalse(any(source["active"] for source in sources))

    def test_active_endpoint_validates_source_id(self) -> None:
        self.assert_error(
            self.client.patch("/api/maps/active", json={"source_id": 999}),
            404,
            "map_source_not_found",
        )
        for value in (True, 0, -1, "1"):
            with self.subTest(value=value):
                self.assert_error(
                    self.client.patch("/api/maps/active", json={"source_id": value}),
                    400,
                    "invalid_source_id",
                )
        self.assert_error(
            self.client.patch("/api/maps/active", json={}),
            400,
            "invalid_field",
        )

    def test_tile_delivery_converts_xyz_y_and_sets_content_type(self) -> None:
        for tile_format, expected_type in (
            ("png", "image/png"),
            ("jpg", "image/jpeg"),
            ("jpeg", "image/jpeg"),
            ("webp", "image/webp"),
        ):
            with self.subTest(tile_format=tile_format):
                item = self.import_map(
                    mbtiles_bytes(tile_format, tile_data=tile_format.encode()),
                    f"{tile_format}.mbtiles",
                ).get_json()["item"]
                # At z=2, XYZ y=1 maps to TMS y=(2**2-1)-1=2.
                response = self.client.get(
                    f"/api/maps/tiles/{item['id']}/2/1/1"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, tile_format.encode())
                self.assertEqual(response.content_type, expected_type)
                self.assertIn("max-age", response.headers["Cache-Control"])
                self.assert_error(
                    self.client.get(f"/api/maps/tiles/{item['id']}/2/1/2"),
                    404,
                    "tile_not_found",
                )

    def test_normalized_tile_delivery_converts_xyz_y(self) -> None:
        item = self.import_map(
            mbtiles_bytes(normalized=True, tile_data=b"normalized")
        ).get_json()["item"]
        response = self.client.get(f"/api/maps/tiles/{item['id']}/2/1/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"normalized")
        self.assertEqual(response.content_type, "image/png")
        self.assert_error(
            self.client.get(f"/api/maps/tiles/{item['id']}/2/1/2"),
            404,
            "tile_not_found",
        )

    def test_tile_path_is_constrained_to_maps_directory(self) -> None:
        with panorama_app.db() as conn:
            source_id = conn.execute(
                """
                INSERT INTO map_sources
                (name, filename, format, active, imported_at)
                VALUES ('Unsicher', '../escape.mbtiles', 'png', 0, 1)
                """
            ).lastrowid
            conn.commit()
        self.assert_error(
            self.client.get(f"/api/maps/tiles/{source_id}/0/0/0"),
            500,
            "invalid_map_path",
        )


if __name__ == "__main__":
    unittest.main()

