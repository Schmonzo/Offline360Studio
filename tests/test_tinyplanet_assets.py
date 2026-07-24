import unittest
from pathlib import Path

import app as panorama_app


class TinyPlanetAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        panorama_app.app.config.update(TESTING=True)
        self.client = panorama_app.app.test_client()
        self.static_root = Path(panorama_app.app.static_folder)

    def test_page_loads_tiny_planet_before_viewer_integration(self) -> None:
        response = self.client.get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)

        tiny_planet = '<script src="/static/js/tinyplanet.js"></script>'
        viewer_integration = '<script src="/static/js/viewer.js"></script>'
        self.assertIn(tiny_planet, page)
        self.assertIn(viewer_integration, page)
        self.assertLess(page.index(tiny_planet), page.index(viewer_integration))

    def test_page_contains_accessible_photo_only_mode_controls_and_status(self) -> None:
        response = self.client.get("/")
        self.addCleanup(response.close)
        page = response.get_data(as_text=True)

        self.assertIn('id="projectionModeControls"', page)
        self.assertIn('aria-label="Projektionsmodus"', page)
        self.assertIn('id="normalModeBtn"', page)
        self.assertIn('id="tinyPlanetBtn"', page)
        self.assertIn('aria-label="Tiny Planet"', page)
        self.assertIn('id="rabbitHoleBtn"', page)
        self.assertIn('aria-label="Rabbit Hole"', page)
        self.assertIn('aria-pressed="false"', page)
        self.assertIn('id="viewModeLabel"', page)
        self.assertIn('role="status"', page)

    def test_tiny_planet_uses_only_local_three_module(self) -> None:
        source = (self.static_root / "js" / "tinyplanet.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("/static/lib/three.module.min.js", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("http://", source)

    def test_renderer_contains_both_stereographic_projections_and_cleanup(self) -> None:
        source = (self.static_root / "js" / "tinyplanet.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("'tiny-planet'", source)
        self.assertIn("'rabbit-hole'", source)
        self.assertIn("1.0 + radius2", source)
        self.assertIn("2.0 * plane.x / denominator", source)
        self.assertIn("poleSign * (1.0 - radius2) / denominator", source)
        self.assertIn("uniform float projectionMode", source)
        self.assertIn("cancelAnimationFrame(this.animationFrame)", source)
        self.assertIn("this.texture?.dispose()", source)
        self.assertIn("this.renderer?.forceContextLoss()", source)

    def test_projection_names_map_to_the_correct_shader_constants(self) -> None:
        source = (self.static_root / "js" / "tinyplanet.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("[PROJECTION_MODES.TINY_PLANET]: 1", source)
        self.assertIn("[PROJECTION_MODES.RABBIT_HOLE]: 0", source)
        self.assertEqual(
            source.count("PROJECTION_UNIFORM_VALUES[this.projectionMode]"),
            2,
        )

    def test_viewer_contains_tiny_planet_and_rabbit_hole_keyboard_bindings(self) -> None:
        source = (self.static_root / "js" / "viewer.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("event.key.toLowerCase() === 't'", source)
        self.assertIn("event.key.toLowerCase() === 'r'", source)
        self.assertIn("event.key === 'Escape'", source)
        self.assertIn("enterProjectionMode('tiny-planet')", source)
        self.assertIn("enterProjectionMode('rabbit-hole')", source)

    def test_tiny_planet_and_three_assets_are_served(self) -> None:
        for path in (
            "/static/js/tinyplanet.js",
            "/static/lib/three.module.min.js",
            "/static/lib/three.core.min.js",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.data), 1000)


if __name__ == "__main__":
    unittest.main()

