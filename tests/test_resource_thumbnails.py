"""资源卡片缩略图生成与封面对应规则测试。"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

class ResourceThumbnailTest(unittest.TestCase):
    def test_teacher_video_uses_cached_first_frame_webp(self) -> None:
        from backend import resources

        with tempfile.TemporaryDirectory() as temp_dir:
            public_dir = Path(temp_dir) / "public"
            video = public_dir / "teacher" / "lesson.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"fake-video")

            frame = io.BytesIO()
            Image.new("RGB", (960, 540), "#336699").save(frame, "PNG")
            ffmpeg_result = SimpleNamespace(stdout=frame.getvalue())

            with (
                patch.object(resources, "PUBLIC_DIR", public_dir),
                patch.object(resources.shutil, "which", return_value="ffmpeg"),
                patch.object(resources.subprocess, "run", return_value=ffmpeg_result) as run,
            ):
                thumbnail_url = resources.teacher_video_cover_url("/teacher/lesson.mp4")
                cached_url = resources.teacher_video_cover_url("/teacher/lesson.mp4")

            self.assertEqual(thumbnail_url, "/teacher/.thumbs/lesson.video.webp")
            self.assertEqual(cached_url, thumbnail_url)
            run.assert_called_once()
            thumbnail = public_dir / "teacher" / ".thumbs" / "lesson.video.webp"
            self.assertTrue(thumbnail.is_file())
            with Image.open(thumbnail) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (640, 360))

    def test_teacher_custom_cover_precedes_generated_default(self) -> None:
        from backend import resources

        row = {
            "id": 1,
            "title": "老师课堂",
            "description": "",
            "year": 2026,
            "category": "teacher",
            "label": "老师驾到",
            "hot": 0,
            "downloads": 0,
            "image": "/teacher/custom-cover.webp",
            "resource_url": "/teacher/lesson.mp4",
            "created_at": None,
            "updated_at": None,
        }
        with patch.object(resources, "teacher_video_cover_url") as generated_cover:
            resource = resources.format_resource(row)

        self.assertEqual(resource["image"], "/teacher/custom-cover.webp")
        generated_cover.assert_not_called()

    def test_teacher_without_custom_cover_uses_generated_default(self) -> None:
        from backend import resources

        row = {
            "id": 1,
            "title": "老师课堂",
            "description": "",
            "year": 2026,
            "category": "teacher",
            "label": "老师驾到",
            "hot": 0,
            "downloads": 0,
            "image": "",
            "resource_url": "/teacher/lesson.mp4",
            "created_at": None,
            "updated_at": None,
        }
        with patch.object(
            resources,
            "teacher_video_cover_url",
            return_value="/teacher/.thumbs/lesson.video.webp",
        ) as generated_cover:
            resource = resources.format_resource(row)

        self.assertEqual(resource["image"], "/teacher/.thumbs/lesson.video.webp")
        generated_cover.assert_called_once_with("/teacher/lesson.mp4")

    def test_activity_cover_uses_first_filename_and_its_thumbnail(self) -> None:
        from backend import resources

        with tempfile.TemporaryDirectory() as temp_dir:
            public_dir = Path(temp_dir) / "public"
            activity_dir = public_dir / "Photos" / "activity"
            activity_dir.mkdir(parents=True)
            for filename, color in (("10.jpg", "blue"), ("2.jpg", "red")):
                Image.new("RGB", (1200, 800), color).save(activity_dir / filename, "JPEG")

            row = {
                "id": 1,
                "activity": "活动",
                "description": "说明",
                "year": 2026,
                "hot": 0,
                "downloads": 0,
                "sort_order": 10,
                "photo_dir": "/Photos/activity/",
                "photo_count": 0,
                "created_at": None,
            }
            with patch.object(resources, "PUBLIC_DIR", public_dir):
                activity = resources.format_photo_activity(row, [])

            self.assertEqual(activity["coverSrc"], "/Photos/activity/2.jpg")
            self.assertEqual(activity["coverThumbSrc"], "/Photos/activity/.thumbs/2.webp")
            self.assertEqual(activity["photoCount"], 2)
            self.assertNotIn("archiveUrl", activity)

    def test_activity_custom_cover_precedes_first_photo(self) -> None:
        from backend import resources

        with tempfile.TemporaryDirectory() as temp_dir:
            public_dir = Path(temp_dir) / "public"
            activity_dir = public_dir / "Photos" / "activity"
            cover = public_dir / "covers" / "activity.jpg"
            activity_dir.mkdir(parents=True)
            cover.parent.mkdir(parents=True)
            Image.new("RGB", (1200, 800), "blue").save(activity_dir / "1.jpg", "JPEG")
            Image.new("RGB", (1200, 800), "red").save(cover, "JPEG")

            row = {
                "id": 1,
                "activity": "活动",
                "description": "说明",
                "year": 2026,
                "hot": 0,
                "downloads": 0,
                "sort_order": 10,
                "photo_dir": "/Photos/activity/",
                "cover_image": "/covers/activity.jpg",
                "photo_count": 0,
                "created_at": None,
            }
            with patch.object(resources, "PUBLIC_DIR", public_dir):
                activity = resources.format_photo_activity(row, [])

            self.assertEqual(activity["coverImage"], "/covers/activity.jpg")
            self.assertEqual(activity["coverSrc"], "/covers/activity.jpg")
            self.assertEqual(activity["coverThumbSrc"], "/covers/.thumbs/activity.webp")

    def test_yearbook_custom_cover_precedes_first_page(self) -> None:
        from backend import resources

        row = {
            "id": 1,
            "title": "Yearbook",
            "description": "",
            "year": 2026,
            "category": "yearbook",
            "label": "Yearbook",
            "hot": 0,
            "downloads": 0,
            "image": "/covers/yearbook.webp",
            "resource_url": "/yearbook/2026/",
            "created_at": None,
            "updated_at": None,
        }
        with patch.object(resources, "yearbook_cover_url") as generated_cover:
            resource = resources.format_resource(row)

        self.assertEqual(resource["coverImage"], "/covers/yearbook.webp")
        self.assertEqual(resource["image"], "/covers/yearbook.webp")
        generated_cover.assert_not_called()

    def test_yearbook_without_custom_cover_uses_first_page(self) -> None:
        from backend import resources

        row = {
            "id": 1,
            "title": "Yearbook",
            "description": "",
            "year": 2026,
            "category": "yearbook",
            "label": "Yearbook",
            "hot": 0,
            "downloads": 0,
            "image": "",
            "resource_url": "/yearbook/2026/",
            "created_at": None,
            "updated_at": None,
        }
        with patch.object(
            resources,
            "yearbook_cover_url",
            return_value="/yearbook/2026/.thumbs/001.webp",
        ) as generated_cover:
            resource = resources.format_resource(row)

        self.assertIsNone(resource["coverImage"])
        self.assertEqual(resource["image"], "/yearbook/2026/.thumbs/001.webp")
        generated_cover.assert_called_once_with("/yearbook/2026/")


if __name__ == "__main__":
    unittest.main()
