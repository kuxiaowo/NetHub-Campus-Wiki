"""前端静态服务冒烟测试。"""

from __future__ import annotations

import os
import threading
import unittest
from urllib.request import urlopen

os.environ["FRONTEND_API_BASE_URL"] = "http://127.0.0.1:33100/api"

from frontend_server import FrontendHandler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


class FrontendServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def fetch(self, path: str) -> tuple[int, bytes, str]:
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=3) as response:
            return response.status, response.read(), response.headers.get_content_type()

    def test_social_pages_and_preview_asset_are_served(self) -> None:
        for path in (
            "/messages.html",
            "/profile.html",
            "/user.html",
            "/announcements.html",
            "/announcement.html",
            "/resource.html",
        ):
            status, body, content_type = self.fetch(path)
            self.assertEqual(status, 200)
            self.assertEqual(content_type, "text/html")
            self.assertIn(b"NetHub", body)

        status, body, content_type = self.fetch("/og.png")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertGreater(len(body), 100_000)

        for path in ("/js/comments.js", "/js/announcements.js", "/js/announcement.js", "/js/resource-detail.js"):
            status, body, content_type = self.fetch(path)
            self.assertEqual(status, 200)
            self.assertIn(content_type, {"application/javascript", "text/javascript"})
            self.assertGreater(len(body), 100)

    def test_runtime_api_config(self) -> None:
        status, body, content_type = self.fetch("/js/config.js")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript")
        self.assertIn(b"http://127.0.0.1:33100/api", body)

    def test_admin_json_transfer_assets_are_served(self) -> None:
        status, body, content_type = self.fetch("/admin.html")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html")
        self.assertIn(b'data-admin-view="transfer"', body)
        self.assertIn(b'id="exportAllDataButton"', body)
        self.assertIn(b'id="dataImportInput"', body)
        self.assertIn(b'id="previewDataImportButton"', body)
        self.assertIn(b'id="confirmDataImportButton"', body)

        status, body, content_type = self.fetch("/js/admin.js")
        self.assertEqual(status, 200)
        self.assertIn(content_type, {"application/javascript", "text/javascript"})
        self.assertIn(b"/admin/data-import/preview", body)
        self.assertIn(b"/admin/data-export", body)
        self.assertIn(b"data-export-project", body)
        self.assertIn(b"data-export-resource", body)
        self.assertIn(b"data-export-photo-activity", body)

    def test_teacher_video_navigation_and_rendering_assets(self) -> None:
        for path in (
            "/index.html",
            "/projects.html",
            "/resources.html",
            "/detail.html",
            "/about.html",
            "/announcement.html",
            "/announcements.html",
            "/messages.html",
            "/profile.html",
            "/resource.html",
            "/user.html",
        ):
            status, body, content_type = self.fetch(path)
            self.assertEqual(status, 200)
            self.assertEqual(content_type, "text/html")
            resource_index = body.find(b'href="/resources.html"')
            teacher_index = body.find(b'href="/resources.html?category=teacher"')
            self.assertGreaterEqual(resource_index, 0, path)
            self.assertGreater(teacher_index, resource_index, path)
            self.assertIn(b'class="nav-new-badge">new</span>', body, path)

        for path in ("/js/resources.js", "/js/resource-detail.js", "/js/admin.js"):
            status, body, content_type = self.fetch(path)
            self.assertEqual(status, 200)
            self.assertIn(content_type, {"application/javascript", "text/javascript"})
            self.assertIn(b"category === 'teacher'", body)
            self.assertIn(b"<video", body)

        status, body, content_type = self.fetch("/resources.html")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html")
        self.assertNotIn(b'id="photoFilters"', body)
        self.assertNotIn("选择活动".encode("utf-8"), body)

        status, body, content_type = self.fetch("/js/admin.js")
        self.assertEqual(status, 200)
        self.assertNotIn(b"name: 'hot'", body)

        status, body, content_type = self.fetch("/js/resources.js")
        self.assertEqual(status, 200)
        self.assertIn(b"data-resource-view-id", body)
        self.assertIn(b"trackResourceView", body)


if __name__ == "__main__":
    unittest.main()
