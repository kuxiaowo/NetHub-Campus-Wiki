"""前端静态服务冒烟测试。"""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ["FRONTEND_API_BASE_URL"] = "http://127.0.0.1:33100/api"

from frontend_server import (  # noqa: E402
    FrontendHandler,
    PUBLIC_DIR,
    accounts_base_url,
    frontend_api_base_url,
)
from http.server import ThreadingHTTPServer  # noqa: E402


class FrontendServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.range_fixture = PUBLIC_DIR / "__range-test__.mp4"
        cls.range_fixture_bytes = bytes(range(256)) * 8
        cls.range_fixture.write_bytes(cls.range_fixture_bytes)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.range_fixture.unlink(missing_ok=True)

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
        self.assertIn(b"https://auth.nethub.wiki", body)

    def test_oidc_frontend_does_not_expose_session_credentials(self) -> None:
        _, shared_script, _ = self.fetch("/js/api.js")
        _, admin_page, _ = self.fetch("/admin.html")
        self.assertIn(b"credentials: 'include'", shared_script)
        self.assertIn(b"/auth/login?returnTo=", shared_script)
        self.assertNotIn(b"campusWikiAuthToken", shared_script)
        self.assertNotIn(b"Authorization", shared_script)
        self.assertNotIn(b'id="createUserButton"', admin_page)
        self.assertIn(b"data-account-center", shared_script)
        self.assertIn("前往账户中心".encode("utf-8"), shared_script)

    def test_accounts_base_url_uses_oidc_issuer(self) -> None:
        with patch.dict(os.environ, {"OIDC_ISSUER": "https://login.example.test/"}):
            self.assertEqual(accounts_base_url(), "https://login.example.test")

    def test_default_api_config_follows_request_hostname(self) -> None:
        with patch.dict(os.environ, {"FRONTEND_API_BASE_URL": "", "API_PORT": "3100"}):
            self.assertEqual(
                frontend_api_base_url("192.168.1.20:3200"),
                "http://192.168.1.20:3100/api",
            )
            self.assertEqual(
                frontend_api_base_url("[fd00::20]:3200"),
                "http://[fd00::20]:3100/api",
            )

    def test_static_files_support_single_byte_ranges(self) -> None:
        request = Request(
            f"http://127.0.0.1:{self.port}/__range-test__.mp4",
            headers={"Range": "bytes=100-199"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.headers["Content-Range"], "bytes 100-199/2048")
            self.assertEqual(response.headers["Content-Length"], "100")
            self.assertEqual(response.read(), self.range_fixture_bytes[100:200])

        request = Request(
            f"http://127.0.0.1:{self.port}/__range-test__.mp4",
            headers={"Range": "bytes=-32"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 2016-2047/2048")
            self.assertEqual(response.read(), self.range_fixture_bytes[-32:])

        request = Request(
            f"http://127.0.0.1:{self.port}/__range-test__.mp4",
            headers={"Range": "bytes=4096-"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 416)
        self.assertEqual(raised.exception.headers["Content-Range"], "bytes */2048")

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
        self.assertIn(b"name: 'assetDir'", body)
        self.assertIn(b"data-project-update-photos", body)
        self.assertIn(b"/updates/reorder", body)
        self.assertIn(b"data-project-update-author-person", body)
        self.assertIn(b"function projectUpdateAuthors", body)
        self.assertNotIn(b"function boundProjectUpdateAuthors", body)
        self.assertIn(b"rows.filter((row) =>", body)
        self.assertIn(b"body.append('authorPersonId'", body)
        self.assertIn(b"data-browse-relative-to", body)
        self.assertIn(b"/admin/files/folders", body)
        self.assertIn(b"/admin/files/folder-upload", body)
        self.assertIn(b"webkitRelativePath", body)
        project_detail = body.split(b"function adminProjectDetail", 1)[1].split(
            b"function findAdminProject", 1
        )[0]
        project_modal = body.split(b"function openProjectModal", 1)[1].split(
            b"let projectUpdateEditorSequence", 1
        )[0]
        self.assertNotIn(b"data-export-project", project_detail)
        self.assertIn(b"data-export-project", project_modal)

    def test_member_binding_is_admin_only_and_nested_in_project_details(self) -> None:
        _, detail_page, _ = self.fetch("/detail.html")
        _, detail_script, _ = self.fetch("/js/detail.js")
        _, user_page, _ = self.fetch("/user.html")
        _, user_script, _ = self.fetch("/js/user.js")
        _, stylesheet, _ = self.fetch("/css/styles.css")
        self.assertNotIn("尚未注册".encode("utf-8"), detail_script)
        self.assertNotIn("认领档案".encode("utf-8"), detail_script)
        self.assertNotIn(b"data-claim-person", detail_script)
        self.assertNotIn(b"/claims", detail_script)
        self.assertNotIn(b'href="tel:', detail_script)
        self.assertNotIn(b'href="mailto:', detail_script)
        self.assertNotIn("发私信".encode("utf-8"), detail_script)
        self.assertNotIn(b"/messages.html?targetUserId=", detail_script)
        self.assertIn(b".detail-state.is-hidden", stylesheet)
        self.assertNotIn("已关联校园档案".encode("utf-8"), user_page)
        self.assertNotIn("已关联校园档案".encode("utf-8"), user_script)
        self.assertIn(b'id="projectUpdateModal"', detail_page)
        self.assertIn(b'id="projectUpdateForm"', detail_page)
        self.assertIn(b"viewerPermissions?.canCreateUpdate", detail_script)
        self.assertIn(b"/updates`,", detail_script)
        self.assertIn(b"body.append('photos'", detail_script)
        self.assertIn(b"data-delete-project-update", detail_script)
        self.assertIn(b"method: 'DELETE'", detail_script)
        self.assertIn(b"MAX_PROJECT_UPDATE_PHOTO_BYTES = 5 * 1024 * 1024", detail_script)
        self.assertIn(b"boundMember.name", detail_script)
        self.assertIn(b"multiple", detail_page)
        self.assertIn("5MB".encode("utf-8"), detail_page)

        _, profile_page, _ = self.fetch("/profile.html")
        _, profile_script, _ = self.fetch("/js/profile.js")
        self.assertNotIn("已关联校园档案".encode("utf-8"), profile_page)
        self.assertNotIn(b"profileVerified", profile_script)
        self.assertNotIn("CAS 档案认领".encode("utf-8"), profile_page)
        self.assertNotIn(b"claimList", profile_page)
        self.assertNotIn(b"/people/me/claims", profile_script)

        _, admin_page, _ = self.fetch("/admin.html")
        _, admin_script, _ = self.fetch("/js/admin.js")
        self.assertNotIn(b'data-admin-view="people"', admin_page)
        self.assertNotIn("人员与认领".encode("utf-8"), admin_page)
        self.assertIn(b'id="messageReportsTable"', admin_page)
        self.assertIn(b'id="messageReportModal"', admin_page)
        self.assertIn(b"commentId=", admin_script)
        self.assertIn(b"data-view-message-report", admin_script)
        self.assertIn(b"data-delete-reported-comment", admin_script)
        self.assertIn(b"data-delete-reported-message", admin_script)
        self.assertIn(b"data-bind-project-member", admin_script)
        self.assertIn(b"members/${encodeURIComponent(member.personId)}/binding", admin_script)
        self.assertIn(b"data-admin-combobox", admin_script)
        self.assertIn(b"<datalist", admin_script)
        self.assertNotIn(b"data-admin-select-search", admin_script)
        self.assertIn("搜索用户名或展示名".encode("utf-8"), admin_script)
        self.assertNotIn(b"/admin/people/", admin_script)
        self.assertNotIn(b"person-claims", admin_script)

        _, about_page, _ = self.fetch("/about.html")
        _, about_script, about_script_type = self.fetch("/js/about.js")
        self.assertNotIn("选择一位成员，通过微信联系。".encode("utf-8"), about_page)
        self.assertEqual(about_page.count(b"data-account-member="), 4)
        self.assertEqual(about_page.count(b"data-member-name"), 4)
        self.assertEqual(about_page.count(b"data-member-contact"), 4)
        self.assertEqual(about_page.count("微信：".encode("utf-8")), 4)
        for member_name in ("Steve 庞正心", "Kipper 田思源", "Nimo 李亦涵", "Brandon 李柏鸿"):
            self.assertIn(member_name.encode("utf-8"), about_page)
        self.assertIn(about_script_type, {"application/javascript", "text/javascript"})
        self.assertIn(b"/projects?search=NetHub", about_script)
        self.assertIn(b"/user.html?id=", about_script)
        self.assertIn(b"member.contactValue", about_script)
        self.assertNotIn(b"data-bind-project-member", about_page)
        self.assertIn("产品 03 · 联合项目".encode("utf-8"), about_page)
        self.assertIn("NetHub 小组与".encode("utf-8"), about_page)
        self.assertIn("Tech".encode("utf-8"), about_page)
        self.assertIn(b'href="https://sdgj.tech"', about_page)
        self.assertIn(b'href="https://todolist.nethub.wiki"', about_page)
        self.assertNotIn(b'href="https://www.nethub.wiki"', about_page)
        self.assertIn(b'src="/assets/about/mood-meter.webp"', about_page)
        self.assertNotIn(b'/assets/nethub-icon.png', about_page)
        self.assertEqual(about_page.count(b'src="/assets/about/nethub-icon.webp"'), 4)

        status, mood_meter, content_type = self.fetch("/assets/about/mood-meter.webp")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/webp")
        self.assertEqual(mood_meter[:4], b"RIFF")
        self.assertEqual(mood_meter[8:12], b"WEBP")

        status, about_icon, content_type = self.fetch("/assets/about/nethub-icon.webp")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/webp")
        self.assertEqual(about_icon[:4], b"RIFF")
        self.assertEqual(about_icon[8:12], b"WEBP")

        _, home_page, _ = self.fetch("/index.html")
        self.assertIn(b'href="https://todolist.nethub.wiki"', home_page)
        self.assertIn(b'class="home-todo-preview" href="https://todolist.nethub.wiki"', home_page)
        self.assertIn(b'src="/assets/about/todolist.webp"', home_page)
        self.assertIn(b'class="about-feature-image-link" href="https://todolist.nethub.wiki"', about_page)

    def test_project_logo_fallback_is_shared_and_fills_the_middle_row(self) -> None:
        _, shared_script, _ = self.fetch("/js/api.js")
        _, detail_script, _ = self.fetch("/js/detail.js")
        _, stylesheet, _ = self.fetch("/css/styles.css")

        self.assertIn(b"PROJECT_LOGO_FALLBACK_MAX_LENGTH = 8", shared_script)
        self.assertIn(b"projectLogoFallbackText", shared_script)
        self.assertIn(b"data-logo-text", shared_script)
        self.assertNotIn(b"charAt(0).toUpperCase()", shared_script)
        self.assertIn(
            b"projectIconImage(project, { className: 'detail-hero-visual project-visual' })",
            detail_script,
        )
        self.assertNotIn(b"initials(project.name)", detail_script)
        self.assertIn(b".project-logo-frame::before", stylesheet)
        self.assertIn(b"text-align-last: justify", stylesheet)

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
        self.assertIn(b"resource.category === 'yearbook'", shared_ui)
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
        _, shared_script, _ = self.fetch("/js/api.js")
        _, detail_script, _ = self.fetch("/js/resource-detail.js")
        self.assertIn(b"ResourceUI.resourceCard", resource_script)
        self.assertIn(b"ResourceUI.activityCard", resource_script)
        self.assertIn(b"mountCommentSection(yearbookComments, 'resource'", resource_script)
        self.assertIn(b"ResourceUI.resourceCard", admin_script)
        self.assertIn(b"ResourceUI.activityCard", admin_script)
        self.assertNotIn(b"<video", resource_script)
        self.assertNotIn(b"<video", admin_script)
        self.assertIn(b"<video", detail_script)
        self.assertIn(b"poster=", detail_script)
        self.assertIn(b"is-video-detail", detail_script)
        self.assertIn(b"?track=false", detail_script)
        self.assertIn(b"window.location.replace", detail_script)
        self.assertIn(b"target.searchParams.set('commentId'", detail_script)
        self.assertNotIn("打开 Yearbook".encode("utf-8"), detail_script)
        self.assertIn(b"preview=admin", admin_script)
        self.assertIn(b"downloadFilesToSelectedDirectory", shared_script)
        self.assertIn(b"downloadFilesToDefaultDirectory", shared_script)
        self.assertIn(b"showDirectoryPicker", shared_script)
        self.assertIn(b"response.body.pipeTo", shared_script)
        self.assertIn("只能将照片批量下载到浏览器的默认下载目录".encode("utf-8"), shared_script)
        self.assertIn("是否允许多个文件下载".encode("utf-8"), shared_script)
        self.assertIn(b"deliveryMode: 'default-directory'", shared_script)
        self.assertIn(b"downloadCurrentActivityPhotos", resource_script)
        self.assertNotIn(b"downloadCurrentActivityArchive", resource_script)
        self.assertNotIn(b"archiveUrl", resource_script)
        self.assertNotIn(b"archiveUrl", admin_script)
        self.assertIn("下载全部照片".encode("utf-8"), resource_page)
        self.assertIn("下载全部照片".encode("utf-8"), admin_page)
        self.assertIn("封面地址（选填）".encode("utf-8"), admin_script)
        self.assertIn("简介（选填）".encode("utf-8"), admin_script)
        self.assertIn("活动简介（选填）".encode("utf-8"), admin_script)
        self.assertIn(b"openResourceModal({ category: adminState.resourceCategory || 'other' })", admin_script)
        self.assertIn(b"function resourceDraftForCategory(resource, category)", admin_script)
        self.assertIn(b"function resourceDraftToActivity(resource)", admin_script)
        self.assertIn(b"function activityDraftToResource(activity, category)", admin_script)
        self.assertIn(b"resource.category || 'other'", admin_script)
        self.assertIn("资源 · ${selectedCategory?.label".encode("utf-8"), admin_script)
        self.assertIn(b"activityFields(activity, { includeCategory: !isEdit })", admin_script)
        self.assertNotIn(b"closeAdminModal();\n      setTimeout(() => openResourceModal", admin_script)
        self.assertNotIn("查看详情与留言".encode("utf-8"), resource_script)
        self.assertIn(b'id="yearbookComments"', resource_page)
        self.assertIn(b'/js/comments.js', resource_page)

        self.assertNotIn(b'id="photoFilters"', resource_page)
        self.assertNotIn("选择活动".encode("utf-8"), resource_page)

        status, body, content_type = self.fetch("/js/admin.js")
        self.assertEqual(status, 200)
        self.assertNotIn(b"name: 'hot'", body)

        self.assertNotIn(b"data-resource-view-id", resource_script)
        self.assertNotIn(b"trackResourceView", resource_script)

    def test_avatar_user_deletion_and_announcement_controls_are_served(self) -> None:
        _, profile_page, _ = self.fetch("/profile.html")
        _, profile_script, _ = self.fetch("/js/profile.js")
        _, admin_script, _ = self.fetch("/js/admin.js")
        _, comments_script, _ = self.fetch("/js/comments.js")
        _, messages_script, _ = self.fetch("/js/messages.js")

        self.assertIn(b'id="profileAvatarInput"', profile_page)
        self.assertIn(b'id="profileAvatarUpload"', profile_page)
        self.assertNotIn("头像地址".encode("utf-8"), profile_page)
        self.assertIn(b"/users/me/avatar", profile_script)
        self.assertIn(b"data-delete-user", admin_script)
        self.assertIn(b"data-delete-announcement", admin_script)
        self.assertNotIn(b"{ value: 'draft'", admin_script)
        self.assertIn(b"comment.author.deleted", comments_script)
        self.assertIn(b"otherUser?.deleted", messages_script)


if __name__ == "__main__":
    unittest.main()
