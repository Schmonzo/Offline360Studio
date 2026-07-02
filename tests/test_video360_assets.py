import unittest
from pathlib import Path

import app as panorama_app


class Video360AssetTests(unittest.TestCase):
    def setUp(self) -> None:
        panorama_app.app.config.update(TESTING=True)
        self.client = panorama_app.app.test_client()

    def test_page_loads_local_video_viewer_before_viewer_integration(self) -> None:
        response = self.client.get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)

        video_viewer = '<script src="/static/js/video360.js"></script>'
        viewer_integration = '<script src="/static/js/viewer.js"></script>'
        self.assertIn(video_viewer, page)
        self.assertIn(viewer_integration, page)
        self.assertLess(page.index(video_viewer), page.index(viewer_integration))

    def test_three_module_and_its_local_core_dependency_are_served(self) -> None:
        module_response = self.client.get("/static/lib/three.module.min.js")
        core_response = self.client.get("/static/lib/three.core.min.js")
        self.addCleanup(module_response.close)
        self.addCleanup(core_response.close)

        self.assertEqual(module_response.status_code, 200)
        self.assertEqual(core_response.status_code, 200)
        self.assertIn(
            b'from"./three.core.min.js"',
            module_response.data,
        )
        self.assertGreater(len(core_response.data), 100_000)

    def test_video_viewer_has_no_remote_runtime_dependency(self) -> None:
        source = (
            Path(panorama_app.app.static_folder) / "js" / "video360.js"
        ).read_text(encoding="utf-8")

        self.assertIn("three.module.min.js", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("http://", source)


if __name__ == "__main__":
    unittest.main()
