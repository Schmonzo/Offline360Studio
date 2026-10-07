import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendInitializationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        cls.admin = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
        cls.offline_maps = (
            ROOT / "static" / "js" / "offline_maps.js"
        ).read_text(encoding="utf-8")

    def test_app_initializes_before_map_module_and_isolates_map_hooks(self) -> None:
        app_script = '<script src="/static/js/app.js"></script>'
        map_script = '<script src="/static/js/map.js"></script>'
        self.assertLess(self.page.index(app_script), self.page.index(map_script))
        self.assertIn("function callOptionalUi(", self.app)
        self.assertIn("callOptionalUi('mapUi', 'setMediaItems'", self.app)

    def test_admin_buttons_are_bound_by_modules_loaded_before_map(self) -> None:
        admin_script = '<script src="/static/js/admin.js"></script>'
        map_script = '<script src="/static/js/map.js"></script>'
        self.assertLess(self.page.index(admin_script), self.page.index(map_script))
        self.assertIn(
            "addHotspotBtn.addEventListener('click', beginHotspotPlacement)",
            self.admin,
        )
        self.assertIn("document.getElementById('adminToggleBtn').onclick", self.app)

    def test_gallery_initialization_precedes_optional_map_notification(self) -> None:
        render = self.app.index("  renderGallery();", self.app.index("async function loadMedia"))
        notify = self.app.index("callOptionalUi('mapUi', 'setMediaItems'", render)
        self.assertLess(render, notify)
        self.assertRegex(self.app, r"\nloadMedia\(\);\s*$")

    def test_offline_maps_tolerates_missing_optional_elements(self) -> None:
        self.assertIn("if (!status) return;", self.offline_maps)
        self.assertIn("if (!list) return;", self.offline_maps)
        self.assertIn("if (form && fileInput && importButton)", self.offline_maps)
        self.assertIn("basemapSelect?.addEventListener", self.offline_maps)

    def test_central_ui_state_is_defined_once_without_global_name_collision(self) -> None:
        scripts = [
            (ROOT / match).read_text(encoding="utf-8")
            for match in re.findall(r'<script src="/(static/js/[^"]+)"', self.page)
        ]
        combined = "\n".join(scripts)
        self.assertEqual(combined.count("window.appUiState ="), 1)
        self.assertEqual(self.app.count("function applyUiState()"), 1)
        self.assertNotRegex(self.app, r"\bconst\s+viewerElement\b")
        self.assertIn("const viewerRootElement", self.app)

    def test_mbtiles_import_controls_remain_in_admin(self) -> None:
        for marker in (
            'id="offlineMapImportForm"',
            'id="offlineMapFile"',
            'accept=".mbtiles"',
            'id="offlineMapImportBtn"',
            'id="offlineMapList"',
            'id="offlineMapStatus"',
        ):
            self.assertIn(marker, self.page)


if __name__ == "__main__":
    unittest.main()

