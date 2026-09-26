from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_media_to_r2.py"
SPEC = importlib.util.spec_from_file_location("campus_media_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.put_calls: list[str] = []

    def head_key(self, key: str):
        payload = self.objects.get(key)
        if payload is None:
            return None
        return SimpleNamespace(
            size=len(payload), etag="test-etag",
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def put_key_file(self, key: str, source: Path, **_kwargs):
        self.put_calls.append(key)
        self.objects[key] = source.read_bytes()
        return SimpleNamespace(etag="uploaded-etag")


def verify_fake_remote(storage: FakeStorage, key: str, digest: str, size: int) -> None:
    payload = storage.objects.get(key)
    if payload is None or len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise migration.MediaStorageError(
            "迁移后回读哈希不一致", status_code=409, code="verification_failed"
        )


class ExistingObjectVerificationTest(unittest.TestCase):
    def test_matching_worker_hash_avoids_download(self) -> None:
        digest = hashlib.sha256(b"example").hexdigest()
        with patch.object(migration, "verify_remote") as download:
            migration.verify_existing_remote(FakeStorage({}), "CAS/example", digest, 7, digest)
        download.assert_not_called()

    def test_missing_worker_hash_downloads_and_compares(self) -> None:
        digest = hashlib.sha256(b"example").hexdigest()
        with patch.object(migration, "verify_remote") as download:
            migration.verify_existing_remote(FakeStorage({}), "CAS/example", digest, 7, None)
        download.assert_called_once()

    def test_conflicting_worker_hash_is_rejected(self) -> None:
        digest = hashlib.sha256(b"example").hexdigest()
        with patch.object(migration, "verify_remote") as download:
            with self.assertRaises(migration.MediaStorageError):
                migration.verify_existing_remote(FakeStorage({}), "CAS/example", digest, 7, "0" * 64)
        download.assert_not_called()


class SafeDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.public = self.project / "public"
        (self.public / "CAS").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_symlink(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"当前平台不允许创建测试符号链接：{exc}")

    def test_rejects_file_symlink_before_reading_target(self) -> None:
        outside = self.project / "secret.pdf"
        outside.write_bytes(b"do-not-read")
        link = self.public / "CAS" / "leak.pdf"
        self.make_symlink(link, outside)

        with patch.object(migration, "PROJECT_ROOT", self.project), self.assertRaises(
            SystemExit
        ) as raised:
            migration.discover([Path("public/CAS")], self.public)

        self.assertIn("符号链接", str(raised.exception))

    def test_rejects_linked_directory_in_path_chain(self) -> None:
        outside = self.project / "outside"
        outside.mkdir()
        (outside / "leak.pdf").write_bytes(b"do-not-read")
        link = self.public / "CAS" / "linked"
        self.make_symlink(link, outside, directory=True)

        with patch.object(migration, "PROJECT_ROOT", self.project), self.assertRaises(
            SystemExit
        ) as raised:
            migration.discover([Path("public/CAS")], self.public)

        self.assertIn("符号链接", str(raised.exception))

    def test_rejects_source_outside_allowed_root(self) -> None:
        outside = self.project / "outside.pdf"
        outside.write_bytes(b"outside")
        with patch.object(migration, "PROJECT_ROOT", self.project), self.assertRaises(
            SystemExit
        ):
            migration.discover([outside], self.public)


class YearbookMigrationMappingTest(unittest.TestCase):
    def test_yearbook_sources_use_only_normalized_r2_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory) / "public"
            yearbook = public / "yearbook" / "2026"
            yearbook.mkdir(parents=True)
            page = yearbook / "001.jpg"
            pdf = yearbook / "yearbook.pdf"
            page.write_bytes(b"page")
            pdf.write_bytes(b"pdf")

            self.assertEqual(
                migration.migration_key(page, public),
                ("yearbook-pages/2026/001.jpg", None),
            )
            self.assertEqual(
                migration.migration_key(pdf, public),
                ("yearbook-pdfs/2026/yearbook.pdf", None),
            )
            self.assertEqual(
                migration.thumbnail_key_for_path("yearbook/2026/001.jpg"),
                "thumbnails/yearbook/2026/001.jpg.image.webp",
            )


class AtomicManifestTest(unittest.TestCase):
    def test_replace_retries_transient_permission_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "checkpoint.json"
            real_replace = migration.os.replace
            attempts = 0

            def flaky_replace(source: Path, destination: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("模拟 Windows 短暂共享冲突")
                real_replace(source, destination)

            with (
                patch.object(migration.os, "replace", side_effect=flaky_replace),
                patch.object(migration.time, "sleep") as sleeper,
            ):
                migration.atomic_json(manifest, {"status": "verified"})

            self.assertEqual(attempts, 3)
            self.assertEqual(sleeper.call_count, 2)
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8")),
                {"status": "verified"},
            )

    def test_replace_raises_after_bounded_permission_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "checkpoint.json"
            with (
                patch.object(
                    migration.os,
                    "replace",
                    side_effect=PermissionError("模拟持续共享冲突"),
                ) as replacer,
                patch.object(migration.time, "sleep") as sleeper,
                self.assertRaises(PermissionError),
            ):
                migration.atomic_json(manifest, {"status": "planned"})

            self.assertEqual(
                replacer.call_count,
                len(migration._ATOMIC_REPLACE_RETRY_DELAYS) + 1,
            )
            self.assertEqual(
                sleeper.call_count,
                len(migration._ATOMIC_REPLACE_RETRY_DELAYS),
            )


class CheckpointVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.source = self.project / "public" / "CAS" / "sample.pdf"
        self.source.parent.mkdir(parents=True)
        self.payload = b"campus-r2-checkpoint"
        self.source.write_bytes(self.payload)
        self.manifest = self.project / "checkpoint.json"
        self.key = "CAS/sample.pdf"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": {
                        "public/CAS/sample.pdf": {
                            "key": self.key,
                            "size": len(self.payload),
                            "sha256": self.digest,
                            "status": "verified",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def args(self, *, execute: bool = True, no_thumbnails: bool = True) -> argparse.Namespace:
        return argparse.Namespace(
            sources=[Path("public/CAS")],
            manifest=self.manifest,
            execute=execute,
            no_thumbnails=no_thumbnails,
        )

    def run_main(self, storage: FakeStorage, *, execute: bool = True) -> int:
        with (
            patch.object(migration, "PROJECT_ROOT", self.project),
            patch.object(migration, "parse_args", return_value=self.args(execute=execute)),
            patch.object(migration, "R2MediaStorage", return_value=storage) as constructor,
            patch.object(migration, "verify_remote", side_effect=verify_fake_remote),
        ):
            result = migration.main()
        if not execute:
            constructor.assert_not_called()
        return result

    def test_verified_checkpoint_reuploads_when_remote_object_was_deleted(self) -> None:
        storage = FakeStorage({})

        self.assertEqual(self.run_main(storage), 0)
        self.assertEqual(storage.put_calls, [self.key])
        self.assertEqual(storage.objects[self.key], self.payload)
        record = json.loads(self.manifest.read_text(encoding="utf-8"))["items"][
            "public/CAS/sample.pdf"
        ]
        self.assertEqual(record["status"], "verified")
        self.assertEqual(record["action"], "uploaded")

    def test_verified_checkpoint_fails_when_remote_object_was_tampered(self) -> None:
        storage = FakeStorage({self.key: b"X" * len(self.payload)})

        self.assertEqual(self.run_main(storage), 1)
        self.assertEqual(storage.put_calls, [])
        record = json.loads(self.manifest.read_text(encoding="utf-8"))["items"][
            "public/CAS/sample.pdf"
        ]
        self.assertEqual(record["status"], "failed")

    def test_dry_run_never_constructs_storage_or_verifies_remote(self) -> None:
        storage = FakeStorage({self.key: self.payload})
        with patch.object(migration, "verify_remote") as verifier:
            self.assertEqual(self.run_main(storage, execute=False), 0)
            verifier.assert_not_called()


class ThumbnailMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.source = self.project / "public" / "CAS" / "photo.png"
        self.source.parent.mkdir(parents=True)
        Image.new("RGB", (32, 24), "navy").save(self.source)
        self.manifest = self.project / "checkpoint.json"
        self.source_key = "CAS/photo.png"
        self.thumb_key = "thumbnails/CAS/photo.png.image.webp"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_main(self, storage: FakeStorage, *, verifier=verify_fake_remote) -> int:
        args = argparse.Namespace(
            sources=[Path("public/CAS")],
            manifest=self.manifest,
            execute=True,
            no_thumbnails=False,
        )
        with (
            patch.object(migration, "PROJECT_ROOT", self.project),
            patch.object(migration, "parse_args", return_value=args),
            patch.object(migration, "R2MediaStorage", return_value=storage),
            patch.object(migration, "verify_remote", side_effect=verifier),
        ):
            return migration.main()

    def test_verified_source_checkpoint_still_repairs_missing_thumbnail(self) -> None:
        source_payload = self.source.read_bytes()
        source_digest = hashlib.sha256(source_payload).hexdigest()
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 2,
                    "items": {
                        "public/CAS/photo.png": {
                            "key": self.source_key,
                            "size": len(source_payload),
                            "sha256": source_digest,
                            "status": "verified",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        storage = FakeStorage({self.source_key: source_payload})

        self.assertEqual(self.run_main(storage), 0)
        self.assertEqual(storage.put_calls, [self.thumb_key])
        record = json.loads(self.manifest.read_text(encoding="utf-8"))["thumbnails"][
            "public/CAS/photo.png"
        ]
        self.assertEqual(record["status"], "verified")
        self.assertEqual(record["key"], self.thumb_key)

    def test_thumbnail_checkpoint_resumes_without_upload(self) -> None:
        storage = FakeStorage({})
        self.assertEqual(self.run_main(storage), 0)
        first_puts = list(storage.put_calls)

        self.assertEqual(self.run_main(storage), 0)
        self.assertEqual(storage.put_calls, first_puts)
        record = json.loads(self.manifest.read_text(encoding="utf-8"))["thumbnails"][
            "public/CAS/photo.png"
        ]
        self.assertEqual(record["status"], "verified")

    def test_failed_thumbnail_verification_recovers_without_reupload(self) -> None:
        storage = FakeStorage({})
        failed_once = False

        def transient_verifier(
            candidate: FakeStorage, key: str, digest: str, size: int
        ) -> None:
            nonlocal failed_once
            if key == self.thumb_key and not failed_once:
                failed_once = True
                raise migration.MediaStorageError("模拟缩略图回读超时")
            verify_fake_remote(candidate, key, digest, size)

        self.assertEqual(self.run_main(storage, verifier=transient_verifier), 1)
        failed_record = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "thumbnails"
        ]["public/CAS/photo.png"]
        self.assertEqual(failed_record["status"], "failed")
        first_puts = list(storage.put_calls)

        self.assertEqual(self.run_main(storage), 0)
        self.assertEqual(storage.put_calls, first_puts)
        recovered_record = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "thumbnails"
        ]["public/CAS/photo.png"]
        self.assertEqual(recovered_record["status"], "verified")

    def test_source_failure_does_not_upload_thumbnail(self) -> None:
        source_payload = self.source.read_bytes()
        storage = FakeStorage({self.source_key: b"X" * len(source_payload)})

        self.assertEqual(self.run_main(storage), 1)
        self.assertEqual(storage.put_calls, [])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertNotIn("public/CAS/photo.png", manifest["thumbnails"])

    def test_existing_different_thumbnail_is_rejected_without_overwrite(self) -> None:
        source_payload = self.source.read_bytes()
        expected_thumbnail = self.project / "expected.webp"
        migration.build_image_thumbnail(self.source, expected_thumbnail)
        wrong_thumbnail = b"X" * expected_thumbnail.stat().st_size
        storage = FakeStorage(
            {self.source_key: source_payload, self.thumb_key: wrong_thumbnail}
        )

        self.assertEqual(self.run_main(storage), 1)
        self.assertEqual(storage.put_calls, [])
        self.assertEqual(storage.objects[self.thumb_key], wrong_thumbnail)
        record = json.loads(self.manifest.read_text(encoding="utf-8"))["thumbnails"][
            "public/CAS/photo.png"
        ]
        self.assertEqual(record["status"], "failed")


class SingleInstanceTest(unittest.TestCase):
    def test_second_lock_holder_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "migration.lock"
            with migration.single_instance_lock(lock_path):
                with self.assertRaisesRegex(SystemExit, "拒绝并发执行"):
                    with migration.single_instance_lock(lock_path):
                        self.fail("第二个迁移实例不应取得锁")


if __name__ == "__main__":
    unittest.main()
