import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import Worker, Completed, Cancelled, validate_url, playlist_url, existing_video_id
from mutagen.id3 import ID3, WXXX


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = dict(folder=self.directory.name, format='mp3', quality='320',
                             thumbnail=False, delay=0, cookies='none')
        self.events = queue.Queue()
        self.worker = Worker([], self.settings, self.events)

    def test_url_host_validation(self):
        self.assertTrue(validate_url('https://www.youtube.com/watch?v=abcdefghijk'))
        self.assertFalse(validate_url('https://youtube.com.evil.example/test'))
        self.assertFalse(validate_url('file:///youtube.com'))
        self.assertFalse(validate_url('https://youtube.com@evil.example'))
        self.assertFalse(validate_url('https://[broken'))

    def test_corrupt_legacy_metadata_does_not_abort_downloads(self):
        file = Path(self.directory.name) / 'corrupt.mp3'
        file.write_bytes(b'ID3\xff\x00\x00\x00\x00\x00\x00')
        self.assertIsNone(existing_video_id(file))

    def test_legacy_mp3_is_recognized_without_renaming(self):
        file = Path(self.directory.name) / 'old-name.mp3'
        tags = ID3()
        tags.add(WXXX(desc='source', url='https://www.youtube.com/watch?v=abcdefghijk'))
        tags.save(file)
        self.assertEqual(existing_video_id(file), 'abcdefghijk')

    def test_playlist_detection_preserves_single_video(self):
        self.assertTrue(playlist_url('https://youtube.com/playlist?list=123'))
        self.assertFalse(playlist_url('https://youtube.com/watch?v=123&list=456'))

    def test_archive_uses_real_files_and_selected_format(self):
        folder = Path(self.directory.name)
        (folder / 'Track [abcdefghijk].mp3').write_bytes(b'audio')
        (folder / 'Other [zyxwvutsrqp].m4a').write_bytes(b'audio')
        (folder / 'Partial [aaaaaaaaaaa].mp3.part').write_bytes(b'audio')
        with patch('engine.binary', return_value='C:/tools/ffmpeg.exe'):
            self.assertEqual(self.worker.options()['download_archive'], {'youtube abcdefghijk'})
            (folder / 'Track [abcdefghijk].mp3').unlink()
            self.assertEqual(self.worker.options()['download_archive'], set())

    def test_metadata_without_thumbnail(self):
        with patch('engine.binary', return_value='C:/tools/ffmpeg.exe'):
            names = [item['key'] for item in self.worker.options()['postprocessors']]
        self.assertIn('FFmpegMetadata', names)
        self.assertNotIn('EmbedThumbnail', names)

    def test_download_finished_does_not_count_before_processing(self):
        self.worker.progress({'status': 'finished'})
        self.assertEqual(self.worker.completed, 0)
        Completed(self.worker).run({'title': 'Track'})
        self.assertEqual(self.worker.completed, 1)

    def test_cancel_interrupts_pause(self):
        self.worker.resume.clear()
        outcome = []
        def wait():
            try:
                self.worker.checkpoint()
            except Cancelled:
                outcome.append('cancelled')
        thread = threading.Thread(target=wait)
        thread.start()
        self.worker.stop.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ['cancelled'])

    def test_failures_are_retained_for_retry(self):
        job = dict(id='test', url='https://youtu.be/abcdefghijk', playlist=False)
        self.worker.jobs = [job]
        with patch.object(self.worker, 'options', return_value={}), patch('engine.YoutubeDL') as downloader:
            downloader.return_value.__enter__.return_value.download.return_value = 1
            self.worker.run()
        result = list(self.events.queue)[-1][1]
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['failed'], [job])

    def test_directory_failure_is_reported(self):
        file = Path(self.directory.name) / 'not-a-directory'
        file.write_text('test')
        self.worker.settings['folder'] = str(file)
        self.worker.run()
        self.assertEqual(list(self.events.queue)[-1][1]['errors'], 1)


if __name__ == '__main__':
    unittest.main()
