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

        status, body, content_type = self.fetch("/messages.html")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html")
        self.assertIn("我的消息".encode("utf-8"), body)
        self.assertIn("回复我的".encode("utf-8"), body)
        self.assertIn("收到的赞".encode("utf-8"), body)

        status, body, _ = self.fetch("/js/comments.js")
        self.assertIn(b"comment-like-button", body)
        self.assertIn(b"/context", body)
        self.assertNotIn("赞 ${comment.likeCount".encode("utf-8"), body)

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
        project_detail = body.split(b"function adminProjectDetail", 1)[1].split(
            b"function findAdminProject", 1
        )[0]
        project_modal = body.split(b"function openProjectModal", 1)[1].split(
            b"let projectUpdateEditorSequence", 1
        )[0]
        self.assertNotIn(b"data-export-project", project_detail)
        self.assertIn(b"data-export-project", project_modal)

    def test_member_binding_is_admin_only_and_nested_in_project_details(self) -> None:
        _, detail_script, _ = self.fetch("/js/detail.js")
        self.assertNotIn("尚未注册".encode("utf-8"), detail_script)
        self.assertNotIn("认领档案".encode("utf-8"), detail_script)
        self.assertNotIn(b"data-claim-person", detail_script)
        self.assertNotIn(b"/claims", detail_script)

        _, profile_page, _ = self.fetch("/profile.html")
        _, profile_script, _ = self.fetch("/js/profile.js")
        self.assertNotIn("CAS 档案认领".encode("utf-8"), profile_page)
        self.assertNotIn(b"claimList", profile_page)
        self.assertNotIn(b"/people/me/claims", profile_script)

        _, admin_page, _ = self.fetch("/admin.html")
        _, admin_script, _ = self.fetch("/js/admin.js")
        self.assertNotIn(b'data-admin-view="people"', admin_page)
        self.assertNotIn("人员与认领".encode("utf-8"), admin_page)
        self.assertIn(b'id="messageReportsTable"', admin_page)
        self.assertIn(b"data-bind-project-member", admin_script)
        self.assertIn(b"members/${encodeURIComponent(member.personId)}/binding", admin_script)
        self.assertNotIn(b"/admin/people/", admin_script)
        self.assertNotIn(b"person-claims", admin_script)

        _, about_page, _ = self.fetch("/about.html")
        _, about_script, about_script_type = self.fetch("/js/about.js")
        self.assertNotIn("选择一位成员，通过微信联系。".encode("utf-8"), about_page)
        self.assertEqual(about_page.count(b"data-account-member="), 4)
        self.assertEqual(about_page.count(b"data-member-name"), 4)
        self.assertEqual(about_page.count(b"data-member-contact"), 4)
        self.assertEqual(about_page.count("微信：".encode("utf-8")), 4)
        for member_name in ("庞正心（Steve）", "田思源（Kipper）", "李亦涵（Nimo）", "李柏鸿（Brandon）"):
            self.assertIn(member_name.encode("utf-8"), about_page)
        self.assertIn(about_script_type, {"application/javascript", "text/javascript"})
        self.assertIn(b"/projects?search=NetHub", about_script)
        self.assertIn(b"/user.html?id=", about_script)
        self.assertIn(b"member.contactValue", about_script)
        self.assertNotIn(b"data-bind-project-member", about_page)

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

        _, resource_page, _ = self.fetch("/resources.html")
        _, admin_page, _ = self.fetch("/admin.html")
        for page in (resource_page, admin_page):
            shared_index = page.index(b"/js/resource-ui.js")
            self.assertGreater(shared_index, page.index(b"/js/api.js"))
            page_script_index = (
                page.index(b"/js/resources.js")
                if b"/js/resources.js" in page
                else page.index(b"/js/admin.js")
            )
            self.assertLess(shared_index, page_script_index)

        for shared_filter_fragment in (
            b"resource-filter-bar",
            b"project-search-card",
            b"project-advanced-filters",
            b"resource-library-layout",
            b"filter-category-sidebar",
        ):
            self.assertIn(shared_filter_fragment, resource_page)
            self.assertIn(shared_filter_fragment, admin_page)

        status, shared_ui, content_type = self.fetch("/js/resource-ui.js")
        self.assertEqual(status, 200)
        self.assertIn(content_type, {"application/javascript", "text/javascript"})
        self.assertIn(b"resource-summary-card", shared_ui)
        self.assertIn(b"resource.title", shared_ui)
        self.assertIn(b"resource.year", shared_ui)
        self.assertIn(b"resource.image", shared_ui)
        self.assertIn(b"activity.coverThumbSrc", shared_ui)
        self.assertIn(b"activity.coverSrc", shared_ui)
        self.assertNotIn(b"<video", shared_ui)
        for hidden_field in (
            b"resource.description",
            b"resource.hot",
            b"resource.downloads",
            b"resource.resourceUrl",
        ):
            self.assertNotIn(hidden_field, shared_ui)
        for hidden_field in (
            b"activity.description",
            b"activity.photoCount",
            b"activity.downloads",
        ):
            self.assertNotIn(hidden_field, shared_ui)

        _, resource_script, _ = self.fetch("/js/resources.js")
        _, admin_script, _ = self.fetch("/js/admin.js")
        _, detail_script, _ = self.fetch("/js/resource-detail.js")
        self.assertIn(b"ResourceUI.resourceCard", resource_script)
        self.assertIn(b"ResourceUI.activityCard", resource_script)
        self.assertIn(b"ResourceUI.resourceCard", admin_script)
        self.assertIn(b"ResourceUI.activityCard", admin_script)
        self.assertNotIn(b"<video", resource_script)
        self.assertNotIn(b"<video", admin_script)
        self.assertIn(b"<video", detail_script)
        self.assertIn(b"?track=false", detail_script)
        self.assertIn(b"preview=admin", admin_script)
        self.assertNotIn("查看详情与留言".encode("utf-8"), resource_script)

        self.assertNotIn(b'id="photoFilters"', resource_page)
        self.assertNotIn("选择活动".encode("utf-8"), resource_page)

        status, body, content_type = self.fetch("/js/admin.js")
        self.assertEqual(status, 200)
        self.assertNotIn(b"name: 'hot'", body)

        self.assertNotIn(b"data-resource-view-id", resource_script)
        self.assertNotIn(b"trackResourceView", resource_script)


if __name__ == "__main__":
    unittest.main()
