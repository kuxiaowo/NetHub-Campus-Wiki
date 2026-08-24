"""管理员文件夹创建与整目录上传测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_DATABASE_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_DATABASE_TEMP_DIR.name) / "campus_wiki_test.db")
os.environ["AUTH_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import admin  # noqa: E402


test_app = FastAPI()
test_app.include_router(admin.router)


class AdminFileManagementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        test_app.dependency_overrides[admin.require_admin_user] = lambda: {
            "id": 1,
            "role": "admin",
            "isActive": True,
        }
        cls.client = TestClient(test_app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        test_app.dependency_overrides.pop(admin.require_admin_user, None)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.public_dir = Path(self.temp_dir.name) / "public"
        self.public_dir.mkdir()
        (self.public_dir / "uploads").mkdir()
        self.public_patch = patch.object(admin, "PUBLIC_DIR", self.public_dir)
        self.public_patch.start()

    def tearDown(self) -> None:
        self.public_patch.stop()
        self.temp_dir.cleanup()

    def test_create_folder_and_list_it(self) -> None:
        response = self.client.post(
            "/api/admin/files/folders",
            json={"parentPath": "uploads", "name": "活动照片"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((self.public_dir / "uploads" / "活动照片").is_dir())
        self.assertEqual(response.json()["data"]["path"], "uploads/活动照片")
        self.assertEqual(response.json()["data"]["url"], "/uploads/活动照片/")

        tree = self.client.get("/api/admin/files/tree", params={"path": "uploads"})
        self.assertEqual(tree.status_code, 200, tree.text)
        self.assertEqual(tree.json()["data"][0]["type"], "folder")
        self.assertEqual(tree.json()["data"][0]["name"], "活动照片")

    def test_create_folder_rejects_conflicts_and_unsafe_names(self) -> None:
        (self.public_dir / "uploads" / "existing").mkdir()
        conflict = self.client.post(
            "/api/admin/files/folders",
            json={"parentPath": "uploads", "name": "existing"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

        for name in ("../escape", "CON", "bad:name", ".."):
            with self.subTest(name=name):
                rejected = self.client.post(
                    "/api/admin/files/folders",
                    json={"parentPath": "uploads", "name": name},
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertFalse((self.public_dir / "escape").exists())

    def test_upload_folder_preserves_names_and_structure(self) -> None:
        response = self.client.post(
            "/api/admin/files/folder-upload",
            data={
                "targetPath": "uploads",
                "relativePaths": ["夏令营/封面.jpg", "夏令营/资料/行程.pdf"],
            },
            files=[
                ("files", ("封面.jpg", b"image-bytes", "image/jpeg")),
                ("files", ("行程.pdf", b"pdf-bytes", "application/pdf")),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["folderUrl"], "/uploads/夏令营/")
        self.assertEqual(response.json()["fileCount"], 2)
        self.assertEqual(response.json()["size"], len(b"image-bytes") + len(b"pdf-bytes"))
        self.assertEqual((self.public_dir / "uploads" / "夏令营" / "封面.jpg").read_bytes(), b"image-bytes")
        self.assertEqual(
            (self.public_dir / "uploads" / "夏令营" / "资料" / "行程.pdf").read_bytes(),
            b"pdf-bytes",
        )

        conflict = self.client.post(
            "/api/admin/files/folder-upload",
            data={"targetPath": "uploads", "relativePaths": ["夏令营/另一张.jpg"]},
            files=[("files", ("另一张.jpg", b"other", "image/jpeg"))],
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertFalse((self.public_dir / "uploads" / "夏令营" / "另一张.jpg").exists())

    def test_upload_folder_rejects_invalid_paths_before_writing(self) -> None:
        invalid_cases = (
            (["../escape/test.jpg"], [("files", ("test.jpg", b"x", "image/jpeg"))]),
            (["one/a.jpg", "two/b.jpg"], [
                ("files", ("a.jpg", b"a", "image/jpeg")),
                ("files", ("b.jpg", b"b", "image/jpeg")),
            ]),
            (["scripts/run.exe"], [("files", ("run.exe", b"x", "application/octet-stream"))]),
        )
        for relative_paths, files in invalid_cases:
            with self.subTest(relative_paths=relative_paths):
                rejected = self.client.post(
                    "/api/admin/files/folder-upload",
                    data={"targetPath": "uploads", "relativePaths": relative_paths},
                    files=files,
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(list((self.public_dir / "uploads").iterdir()), [])

    def test_upload_folder_rolls_back_when_a_file_is_too_large(self) -> None:
        with patch.object(admin, "MAX_UPLOAD_BYTES", 3):
            response = self.client.post(
                "/api/admin/files/folder-upload",
                data={
                    "targetPath": "uploads",
                    "relativePaths": ["rollback/ok.jpg", "rollback/large.pdf"],
                },
                files=[
                    ("files", ("ok.jpg", b"ok", "image/jpeg")),
                    ("files", ("large.pdf", b"1234", "application/pdf")),
                ],
            )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertFalse((self.public_dir / "uploads" / "rollback").exists())


if __name__ == "__main__":
    unittest.main()
