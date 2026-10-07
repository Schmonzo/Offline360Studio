import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

    def panel_source(self, panel_id: str, next_panel_id: str | None = None) -> str:
        start = self.page.index(f'id="{panel_id}"')
        end = self.page.index(f'id="{next_panel_id}"', start) if next_panel_id else len(self.page)
        return self.page[start:end]

    def test_navigation_contains_seven_accessible_sections(self) -> None:
        expected = [
            ("media", "Medien"),
            ("projects", "Projekte / Touren"),
            ("hotspots", "Hotspots"),
            ("maps", "Karten &amp; GPS"),
            ("backup", "Backup / Restore"),
            ("export", "Export"),
            ("system", "System"),
        ]
        tabs = re.findall(
            r'<button[^>]+role="tab"[^>]+data-admin-section="([^"]+)"[^>]*>(.*?)</button>',
            self.page,
        )
        self.assertEqual(tabs, expected)
        self.assertIn('role="tablist"', self.page)
        self.assertEqual(self.page.count('role="tabpanel"'), 7)

    def test_media_is_the_default_section(self) -> None:
        media_tab = re.search(r'<button id="adminTabMedia"[^>]+>', self.page)
        media_panel = re.search(r'<section id="adminSectionMedia"[^>]+>', self.page)
        self.assertIsNotNone(media_tab)
        self.assertIsNotNone(media_panel)
        self.assertIn('aria-selected="true"', media_tab.group())
        self.assertNotIn(" hidden", media_panel.group())
        self.assertIn("const DEFAULT_ADMIN_SECTION = 'media';", self.app)

    def test_maps_export_and_system_controls_are_in_their_panels(self) -> None:
        maps = self.panel_source("adminSectionMaps", "adminSectionBackup")
        export = self.panel_source("adminSectionExport", "adminSectionSystem")
        system = self.panel_source("adminSectionSystem")
        for control_id in ("gpsForm", "gpxImportForm", "offlineMapImportForm", "offlineMapList"):
            self.assertIn(f'id="{control_id}"', maps)
        self.assertIn('id="portableExportForm"', export)
        self.assertIn('id="portableExportBtn"', export)
        self.assertIn('id="diagnosticsData"', system)
        self.assertIn("/api/diagnostics/report", system)
        self.assertIn(
            "panel.hidden = panel.dataset.adminPanel !== activeSection;",
            self.app,
        )

    def test_important_existing_control_ids_remain_available(self) -> None:
        important_ids = (
            "rescanBtn",
            "uploadProject",
            "dropZone",
            "fileInput",
            "editForm",
            "projectAdmin",
            "adminProjectSelect",
            "projectForm",
            "projectMediaEditor",
            "saveStartViewBtn",
            "resetStartViewBtn",
            "addHotspotBtn",
            "gpsForm",
            "gpxImportForm",
            "offlineMapImportForm",
            "portableExportForm",
            "exportWithoutMediaBtn",
            "exportWithMediaBtn",
            "restoreForm",
            "diagnosticsData",
            "statusBox",
        )
        for control_id in important_ids:
            self.assertEqual(self.page.count(f'id="{control_id}"'), 1, control_id)

    def test_invalid_local_storage_value_falls_back_to_media(self) -> None:
        self.assertIn("const ADMIN_SECTION_STORAGE_KEY = 'ps_admin_section';", self.app)
        self.assertRegex(
            self.app,
            r"adminSectionTabs\.some\(tab => tab\.dataset\.adminSection === storedSection\)"
            r"\s*\? storedSection\s*: DEFAULT_ADMIN_SECTION",
        )
        self.assertIn("setAdminSection(readStoredAdminSection());", self.app)
        self.assertIn("localStorage.setItem(ADMIN_SECTION_STORAGE_KEY, activeSection)", self.app)

    def test_keyboard_and_focus_navigation_are_present(self) -> None:
        for key in ("ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"):
            self.assertIn(f"'{key}'", self.app)
        self.assertIn(".admin-nav-item:focus-visible", self.css)
        self.assertIn('tab.setAttribute(\'aria-selected\', String(selected))', self.app)
        self.assertIn("tab.tabIndex = selected ? 0 : -1", self.app)

    def test_map_controls_are_hidden_while_admin_is_open(self) -> None:
        self.assertIn(
            "const mapControlsVisible = uiState.mapViewActive && !uiState.adminOpen",
            self.app,
        )
        self.assertIn("mapControlsElement.inert = !mapControlsVisible", self.app)
        self.assertIn(".admin-panel.hidden { display:none; pointer-events:none; }", self.css)

    def test_legacy_version_does_not_reappear(self) -> None:
        legacy_version = "v0." + "3.1"
        checked_sources = [
            self.page,
            self.app,
            (ROOT / "app.py").read_text(encoding="utf-8"),
            (ROOT / "core" / "version.py").read_text(encoding="utf-8"),
        ]
        self.assertNotIn(legacy_version, "\n".join(checked_sources))


if __name__ == "__main__":
    unittest.main()

