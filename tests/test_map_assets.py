from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MapAssetTests(unittest.TestCase):
    def test_leaflet_194_is_local_and_loaded_before_map_module(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        leaflet_script = '<script src="/static/lib/leaflet/leaflet.js"></script>'
        map_script = '<script src="/static/js/map.js"></script>'
        self.assertIn(
            '<link rel="stylesheet" href="/static/lib/leaflet/leaflet.css" />',
            page,
        )
        self.assertLess(page.index(leaflet_script), page.index(map_script))
        leaflet = (ROOT / "static" / "lib" / "leaflet" / "leaflet.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("Leaflet 1.9.4", leaflet)
        self.assertTrue((ROOT / "static" / "lib" / "leaflet" / "LICENSE.txt").is_file())

    def test_map_defaults_to_no_network_tile_layer_and_safe_text_rendering(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertNotIn("tileLayer", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("http://", source)
        self.assertNotIn(".innerHTML", source)
        self.assertNotIn("alert(", source)
        self.assertIn("textContent", source)

    def test_map_and_admin_mount_points_are_accessible(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="mapView"',
            'aria-label="Kartenansicht"',
            'id="stageModeBtn"',
            'aria-pressed="false"',
            'id="gpsStatus"',
            'aria-live="polite"',
            'id="gpxTrackList"',
        ):
            self.assertIn(marker, page)


if __name__ == "__main__":
    unittest.main()
