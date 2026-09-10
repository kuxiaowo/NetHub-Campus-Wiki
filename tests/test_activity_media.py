"""Mixed activity directory scanning, counts, caching and media API contracts."""

import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from backend import resources
from backend.schemas import PhotoActivity, PhotoActivityPhotosResponse


class ActivityMediaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'activity'
        self.directory.mkdir()
        root_patch = patch.object(resources, 'PUBLIC_DIR', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        resources._PHOTO_DIR_CACHE.clear()
        self.addCleanup(resources._PHOTO_DIR_CACHE.clear)
        frame = io.BytesIO()
        Image.new('RGB', (960, 540), 'blue').save(frame, 'PNG')
        self.frame = SimpleNamespace(stdout=frame.getvalue())
        self.row = dict(id=1, activity='混合活动', description='', year=2026,
                        hot=0, downloads=0, sort_order=0, photo_dir='/activity/',
                        photo_count=0, created_at=None)

    def photo(self, name):
        path = self.directory / name
        Image.new('RGB', (80, 40), 'red').save(path)
        return path

    def video(self, name):
        path = self.directory / name
        path.write_bytes(b'video')
        return path

    def test_mixed_order_counts_cover_and_api(self):
        self.photo('10.jpg')
        self.video('2.MP4')
        self.photo('3.png')
        self.video('11.webm')
        (self.directory / 'notes.txt').write_text('ignored')
        (self.directory / 'nested').mkdir()
        (self.directory / 'nested' / '1.mp4').write_bytes(b'ignored')
        with patch.object(resources.shutil, 'which', return_value='ffmpeg'), \
                patch.object(resources.subprocess, 'run', return_value=self.frame) as run:
            summary = resources.format_photo_activity(self.row, [])
            self.assertEqual(run.call_count, 1)  # Summary only generates the cover.
            items = resources._scan_photo_dir('/activity/')
        self.assertEqual([item['title'] for item in items], ['2', '3', '10', '11'])
        self.assertEqual([item['type'] for item in items], ['video', 'image', 'image', 'video'])
        self.assertEqual((summary['photoCount'], summary['videoCount'], summary['mediaCount']), (2, 2, 4))
        self.assertEqual(summary['coverSrc'], '/activity/.thumbs/2.MP4.video.webp')
        response = PhotoActivityPhotosResponse(data=items, activity=summary).model_dump()
        self.assertEqual(response['data'][0]['type'], 'video')
        self.assertEqual(response['activity']['coverType'], 'video')

    def test_video_only_missing_thumbnail_never_uses_video_as_cover(self):
        self.video('1.mov')
        with patch.object(resources.shutil, 'which', return_value=None):
            summary = resources.format_photo_activity(self.row, [])
            items = resources._scan_photo_dir('/activity/')
        self.assertEqual((summary['photoCount'], summary['videoCount'], summary['mediaCount']), (0, 1, 1))
        self.assertIsNone(summary['coverSrc'])
        self.assertIsNone(summary['coverThumbSrc'])
        self.assertEqual(summary['coverType'], 'video')
        self.assertEqual(items[0]['src'], '/activity/1.mov')

    def test_custom_cover_skips_video_generation(self):
        self.video('1.mp4')
        self.photo('cover.jpg')
        with patch.object(resources, '_ensure_video_thumbnail') as generate:
            summary = resources.format_photo_activity({**self.row, 'cover_image': '/activity/cover.jpg'}, [])
        generate.assert_not_called()
        self.assertEqual(summary['coverType'], 'image')
        self.assertEqual(summary['coverSrc'], '/activity/cover.jpg')

    def test_same_stem_files_have_distinct_thumbnails_and_cache_rebuilds(self):
        self.photo('same.jpg')
        self.photo('same.png')
        video = self.video('same.mp4')
        self.video('same.mov')
        with patch.object(resources.shutil, 'which', return_value='ffmpeg'), \
                patch.object(resources.subprocess, 'run', return_value=self.frame) as run:
            items = resources._scan_photo_dir('/activity/')
            again = resources._scan_photo_dir('/activity/')
            self.assertEqual(items, again)
            self.assertEqual(run.call_count, 2)
            os.utime(video, (video.stat().st_atime, video.stat().st_mtime + 10))
            resources._scan_photo_dir('/activity/')
            self.assertEqual(run.call_count, 3)
            self.photo('new.jpg')
            self.assertEqual(len(resources._scan_photo_dir('/activity/')), 5)
            (self.directory / 'new.jpg').unlink()
            self.assertEqual(len(resources._scan_photo_dir('/activity/')), 4)
        self.assertEqual(len({item['thumbSrc'] for item in items}), 4)

    def test_thumbnail_errors_do_not_abort_activity(self):
        self.video('1.mp4')
        for failure in [subprocess.TimeoutExpired('ffmpeg', 1),
                        subprocess.CalledProcessError(1, 'ffmpeg'), OSError('failed')]:
            with self.subTest(failure=failure), \
                    patch.object(resources.shutil, 'which', return_value='ffmpeg'), \
                    patch.object(resources.subprocess, 'run', side_effect=failure):
                self.assertIsNone(resources._format_photo_file(self.directory / '1.mp4', 1)['thumbSrc'])
        with patch.object(resources.shutil, 'which', return_value='ffmpeg'), \
                patch.object(resources.subprocess, 'run', return_value=SimpleNamespace(stdout=b'corrupt')):
            self.assertIsNone(resources._format_photo_file(self.directory / '1.mp4', 1)['thumbSrc'])

    def test_legacy_photos_are_explicit_images(self):
        conn = MagicMock()
        cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {**self.row, 'photo_dir': None, 'photo_count': 1}
        cursor.fetchall.return_value = [dict(id=1, title='photo', image_url='/old.jpg', sort_order=0)]
        with patch.object(resources, 'get_db_connection', return_value=conn):
            detail = resources.get_activity_photo_detail(1)
        self.assertEqual(detail['photos'][0]['type'], 'image')
        self.assertEqual(PhotoActivity(**detail['activity']).mediaCount, 1)

    def test_count_sort_uses_total_including_videos(self):
        conn = MagicMock()
        cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [[dict(id=1), dict(id=2)], []]
        summaries = [dict(id=1, sortOrder=0, photoCount=3, mediaCount=3, createdAt=None),
                     dict(id=2, sortOrder=0, photoCount=0, mediaCount=4, createdAt=None)]
        with patch.object(resources, 'get_db_connection', return_value=conn), \
                patch.object(resources, 'format_photo_activity', side_effect=summaries):
            self.assertEqual([item['id'] for item in resources.list_photo_activities(sort='photoCount')], [2, 1])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is not on PATH')
    def test_real_ffmpeg_first_frame(self):
        video = self.directory / 'real.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=blue:s=160x90:d=1', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p',
                        str(video)], check=True, capture_output=True, timeout=20)
        thumb = resources._ensure_video_thumbnail(video)
        self.assertIsNotNone(thumb)
        with Image.open(self.root / thumb.lstrip('/')) as image:
            self.assertEqual(image.size, (640, 360))


if __name__ == '__main__':
    unittest.main()
