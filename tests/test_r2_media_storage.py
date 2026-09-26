"""R2 adapter HMAC, path mapping, pagination cursor and bounded upload tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend import media_storage


class FakeResponse:
    def __init__(self, status: int = 200, payload=None, headers=None) -> None:
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class R2MediaStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            r2_media_gateway_url="https://wiki-media.example.test",
            r2_media_hmac_secret="中" * 32,
            r2_request_timeout_seconds=5,
            r2_direct_upload_max_bytes=8,
            r2_multipart_part_bytes=5,
            r2_download_url_seconds=90,
            thumbnail_max_width=640,
            thumbnail_max_height=640,
            thumbnail_webp_quality=82,
            thumbnail_webp_method=6,
            media_storage_backend="r2",
            app_environment="production",
        )
        self.patch = patch.object(media_storage, "settings", self.settings)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_chinese_key_internal_hmac_matches_frozen_v1_protocol(self) -> None:
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(payload={"objects": [], "nextCursor": None, "hasMore": False})

        with patch.object(media_storage.requests, "request", side_effect=request), patch.object(media_storage.time, "time", return_value=1720000000):
            media_storage.R2MediaStorage().list_key_prefix("Photos/中文 活动/", limit=50)

        method, url, kwargs = calls[0]
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query, {})  # requests receives params separately.
        target = "/internal/list?limit=50&prefix=Photos%2F%E4%B8%AD%E6%96%87%20%E6%B4%BB%E5%8A%A8%2F"
        body_hash = media_storage.EMPTY_SHA256
        canonical = f"v1\nGET\n{target}\n1720000000\n{body_hash}"
        expected = hmac.new(("中" * 32).encode(), canonical.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(method, "GET")
        self.assertEqual(kwargs["headers"]["X-Media-Signature"], expected)
        self.assertEqual(kwargs["params"], {"prefix": "Photos/中文 活动/", "limit": "50"})

    def test_direct_upload_hashes_body_and_never_overwrites(self) -> None:
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "HEAD":
                return FakeResponse(404)
            return FakeResponse(201, {"etag": '"new"'})

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "中文.jpg"
            source.write_bytes(b"image")
            with patch.object(media_storage.requests, "request", side_effect=request):
                result = media_storage.R2MediaStorage().put_file("Photos/活动/中文.jpg", source)
        put = next(item for item in calls if item[0] == "PUT")
        self.assertEqual(result.sha256, hashlib.sha256(b"image").hexdigest())
        self.assertEqual(put[2]["headers"]["Content-Length"], "5")
        self.assertEqual(put[2]["headers"]["Content-Type"], "image/jpeg")
        self.assertIn("/internal/object/Photos/%E6%B4%BB%E5%8A%A8/%E4%B8%AD%E6%96%87.jpg", put[1])

    def test_large_upload_uses_multipart_and_completes_sorted_parts(self) -> None:
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "HEAD":
                return FakeResponse(404)
            if method == "POST" and "uploadId" not in (kwargs.get("params") or {}):
                return FakeResponse(201, {"uploadId": "upload-1"})
            if method == "PUT":
                number = int(url.rsplit("/", 1)[1])
                return FakeResponse(200, {"partNumber": number, "etag": f"etag-{number}"})
            return FakeResponse(201, {"etag": '"done"'})

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "book.pdf"
            source.write_bytes(b"0123456789AB")
            with patch.object(media_storage.requests, "request", side_effect=request):
                media_storage.R2MediaStorage().put_file("yearbook/中文/book.pdf", source)
        completion = [item for item in calls if item[0] == "POST" and (item[2].get("params") or {}).get("uploadId")][0]
        payload = json.loads(completion[2]["data"])
        self.assertEqual(payload["parts"], [
            {"partNumber": 1, "etag": "etag-1"},
            {"partNumber": 2, "etag": "etag-2"},
            {"partNumber": 3, "etag": "etag-3"},
        ])

    def test_download_signature_is_method_bound_and_short_lived(self) -> None:
        with patch.object(media_storage.time, "time", return_value=1720000000):
            storage = media_storage.R2MediaStorage()
            get_url = storage.download_url("yearbook/中文/book.pdf")
            head_url = storage.download_url("yearbook/中文/book.pdf", method="HEAD")
        self.assertNotEqual(parse_qs(urlsplit(get_url).query)["sig"], parse_qs(urlsplit(head_url).query)["sig"])
        self.assertEqual(parse_qs(urlsplit(get_url).query)["expires"], ["1720000090"])
        self.assertEqual(urlsplit(get_url).path, "/download/yearbook-pdfs/%E4%B8%AD%E6%96%87/book.pdf")

    def test_yearbook_pages_are_public_but_pdfs_require_signed_downloads(self) -> None:
        storage = media_storage.R2MediaStorage()
        self.assertEqual(
            storage.public_url("yearbook/2026/001.jpg"),
            "https://wiki-media.example.test/media/yearbook-pages/2026/001.jpg",
        )
        self.assertEqual(
            storage.public_url(media_storage.thumbnail_key_for_path("yearbook/2026/001.jpg")),
            "https://wiki-media.example.test/media/thumbnails/yearbook/2026/001.jpg.image.webp",
        )
        with self.assertRaises(media_storage.MediaStorageError) as raised:
            storage.public_url("yearbook/2026/yearbook.pdf")
        self.assertEqual(raised.exception.code, "private_object")

    def test_key_mapping_normalizes_yearbook_into_three_fixed_namespaces(self) -> None:
        self.assertIsNone(media_storage.object_key_for_path("Photos/活动/现场.mp4"))
        self.assertEqual(media_storage.object_key_for_path("yearbook/2026/第一页.jpg"), "yearbook-pages/2026/第一页.jpg")
        self.assertEqual(media_storage.object_key_for_path("yearbook/2026/yearbook.pdf"), "yearbook-pdfs/2026/yearbook.pdf")
        self.assertEqual(media_storage.thumbnail_key_for_path("yearbook/2026/第一页.jpg"), "thumbnails/yearbook/2026/第一页.jpg.image.webp")
        self.assertEqual(media_storage.object_prefix_for_directory("yearbook/2026", images=True), "yearbook-pages/2026/")
        self.assertEqual(media_storage.object_prefix_for_directory("yearbook/2026", images=False), "yearbook-pdfs/2026/")
        self.assertEqual(media_storage.logical_path_from_key("yearbook-pages/2026/第一页.jpg"), "yearbook/2026/第一页.jpg")
        self.assertEqual(media_storage.logical_path_from_key("yearbook-pdfs/2026/yearbook.pdf"), "yearbook/2026/yearbook.pdf")
        self.assertEqual(media_storage.object_key_for_path("uploads/资料.pdf"), "project-media/uploads/资料.pdf")
        self.assertEqual(media_storage.logical_path_from_key("avatars/1/a.webp"), "uploads/avatars/1/a.webp")

    def test_yearbook_namespace_rejects_wrong_file_classes_and_old_r2_prefixes(self) -> None:
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.object_key_for_path("yearbook/2026/notes.docx")
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.object_key_for_path("yearbook-pages/2026/book.pdf")
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.object_key_for_path("yearbook-pdfs/2026/001.jpg")
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.object_key_for_path("yearbook-thumbnails/2026/001.jpg")
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.object_prefix_for_directory("yearbook-thumbnails/2026")

    def test_opaque_cursor_rejects_tampering(self) -> None:
        value = media_storage.encode_page_cursor({"workerCursor": "opaque", "seen": 50})
        self.assertEqual(media_storage.decode_page_cursor(value)["seen"], 50)
        with self.assertRaises(media_storage.MediaStorageError):
            media_storage.decode_page_cursor(value[:-1] + ("A" if value[-1] != "A" else "B"))


if __name__ == "__main__":
    unittest.main()
