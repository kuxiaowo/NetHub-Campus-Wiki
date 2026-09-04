"""Backend-hosted public media delivery tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-with-at-least-32-bytes")

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth, main, media, project_assets, resources  # noqa: E402


class PublicMediaUrlTest(unittest.TestCase):
    def test_local_media_url_uses_configured_backend_origin(self) -> None:
        configured = SimpleNamespace(public_media_base_url="https://139.196.41.200/media")
        with patch.object(media, "settings", configured):
            self.assertEqual(
                media.public_media_url("/Photos/校园 活动/封面.jpg"),
                "https://139.196.41.200/media/Photos/%E6%A0%A1%E5%9B%AD%20%E6%B4%BB%E5%8A%A8/%E5%B0%81%E9%9D%A2.jpg",
            )
            self.assertEqual(
                media.local_public_path(
                    "https://139.196.41.200/media/Photos/"
                    "%E6%A0%A1%E5%9B%AD%20%E6%B4%BB%E5%8A%A8/%E5%B0%81%E9%9D%A2.jpg"
                ),
                "Photos/校园 活动/封面.jpg",
            )

    def test_documents_remain_on_authenticated_download_path(self) -> None:
        configured = SimpleNamespace(public_media_base_url="https://139.196.41.200/media")
        with patch.object(media, "settings", configured):
            self.assertEqual(media.public_media_url("/yearbook/book.pdf"), "/yearbook/book.pdf")
            self.assertEqual(
                media.public_media_url("https://cdn.example.com/photo.jpg"),
                "https://cdn.example.com/photo.jpg",
            )

    def test_unsafe_local_paths_are_not_rewritten(self) -> None:
        configured = SimpleNamespace(public_media_base_url="https://139.196.41.200/media")
        with patch.object(media, "settings", configured):
            self.assertIsNone(media.local_public_path("/Photos/../secret.jpg"))
            self.assertEqual(media.public_media_url("/Photos/../secret.jpg"), "/Photos/../secret.jpg")

    def test_api_formatters_return_backend_media_urls(self) -> None:
        configured = SimpleNamespace(public_media_base_url="https://139.196.41.200/media")
        with patch.object(media, "settings", configured):
            resource = resources.format_resource(
                {
                    "id": 4,
                    "title": "老师驾到",
                    "description": "",
                    "year": 2026,
                    "category": "teacher",
                    "label": "老师驾到",
                    "hot": 0,
                    "downloads": 0,
                    "image": "/teacher on stage/cover.webp",
                    "resource_url": "/teacher on stage/Tony.mp4",
                }
            )
            self.assertEqual(
                resource["image"],
                "https://139.196.41.200/media/teacher%20on%20stage/cover.webp",
            )
            self.assertEqual(
                resource["resourceUrl"],
                "https://139.196.41.200/media/teacher%20on%20stage/Tony.mp4",
            )
            self.assertEqual(
                project_assets.project_asset_url("/CAS/NetHub/", "updates/demo.jpg"),
                "https://139.196.41.200/media/CAS/NetHub/updates/demo.jpg",
            )
            user = auth.format_user(
                {
                    "id": 1,
                    "username": "student",
                    "display_name": "Student",
                    "avatar_url": "/uploads/avatars/1/avatar.webp",
                    "role": "user",
                    "is_active": 1,
                }
            )
            self.assertEqual(
                user["avatarUrl"],
                "https://139.196.41.200/media/uploads/avatars/1/avatar.webp",
            )


class PublicMediaRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.public_dir = Path(self.temp_dir.name) / "public"
        media_dir = self.public_dir / "Photos" / "校园 活动"
        media_dir.mkdir(parents=True)
        self.image = media_dir / "封面.jpg"
        self.image.write_bytes(b"0123456789")
        (media_dir / "资料.pdf").write_bytes(b"private-document")
        self.public_patch = patch.object(main, "PUBLIC_DIR", self.public_dir)
        self.public_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.public_patch.stop()
        self.temp_dir.cleanup()

    def test_media_route_serves_files_and_byte_ranges(self) -> None:
        response = self.client.get("/media/Photos/校园%20活动/封面.jpg")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"0123456789")
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cross-origin-resource-policy"], "cross-origin")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

        partial = self.client.get(
            "/media/Photos/校园%20活动/封面.jpg",
            headers={"Range": "bytes=2-5"},
        )
        self.assertEqual(partial.status_code, 206, partial.text)
        self.assertEqual(partial.content, b"2345")
        self.assertEqual(partial.headers["content-range"], "bytes 2-5/10")

        head = self.client.head("/media/Photos/校园%20活动/封面.jpg")
        self.assertEqual(head.status_code, 200, head.text)
        self.assertEqual(head.content, b"")
        self.assertEqual(head.headers["content-length"], "10")

    def test_media_route_does_not_expose_documents(self) -> None:
        response = self.client.get("/media/Photos/校园%20活动/资料.pdf")
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
