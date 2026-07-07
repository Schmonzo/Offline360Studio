from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectAssetTests(unittest.TestCase):
    def test_header_loads_central_version_without_concrete_fallback(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="appVersion">Version unbekannt</span>', page)
        self.assertIn("fetch('/api/version'", source)
        self.assertIn("versionElement.textContent = `v${payload.version}`", source)

    def test_project_card_and_cover_preview_mount_points_exist(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="projectCardsSection"', page)
        self.assertIn('id="projectCards"', page)
        self.assertIn('id="projectCoverPreview"', page)

    def test_project_selection_persistence_and_safe_card_rendering(self) -> None:
        source = (ROOT / "static" / "js" / "projects.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("'ps_active_project_id'", source)
        self.assertIn("'ps_active_project_media_id'", source)
        self.assertIn("restoreStoredTour()", source)
        self.assertIn("card.type = 'button'", source)
        self.assertIn("name.textContent = project.name", source)
        self.assertNotIn(".innerHTML", source)

    def test_project_media_assignment_supports_multiple_selection(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "js" / "projects.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="projectMediaSelect" multiple', page)
        self.assertIn("Strg oder Shift", page)
        self.assertIn("selectedProjectMediaIds()", source)
        self.assertIn("projectMediaSelect.selectedOptions", source)
        self.assertIn("for (const mediaId of mediaIds)", source)
        self.assertIn("JSON.stringify({ media_id: mediaId })", source)

    def test_project_cards_have_visible_focus_and_responsive_rules(self) -> None:
        styles = (ROOT / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".project-card:focus-visible", styles)
        self.assertIn("@media (max-width: 600px)", styles)


if __name__ == "__main__":
    unittest.main()
