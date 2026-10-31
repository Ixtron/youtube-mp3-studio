import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
            instance = downloader.return_value.__enter__.return_value
            instance.in_download_archive.return_value = False
            instance.extract_info.side_effect = lambda *a, **k: self.worker.error('Unavailable')
            self.worker.run()
        result = list(self.events.queue)[-1][1]
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['failed'], [job])

    def test_playlist_counts_saved_existing_and_failed_tracks_separately(self):
        job = dict(id='playlist', url='https://youtube.com/playlist?list=test', playlist=True)
        self.worker.jobs = [job]
        entries = [dict(id=str(i), url=f'https://youtu.be/{i:011}', title=f'Track {i}') for i in range(4)]
        reader, downloader = Mock(), Mock()
        reader.extract_info.return_value = {'entries': entries}
        downloader.in_download_archive.side_effect = lambda entry: entry['id'] == '1'
        def download(url, download):
            if url.endswith('2'):
                self.worker.error('Unavailable')
            else:
                self.worker.progress({'status': 'finished'})
                # No completed item is counted while FFmpeg is still running.
                self.assertEqual(self.worker.tally['processed'], int(url[-1]))
                Completed(self.worker).run({'title': 'Track'})
        downloader.extract_info.side_effect = download
        factory = Mock(side_effect=[reader, downloader])
        reader.__enter__ = Mock(return_value=reader)
        reader.__exit__ = Mock(return_value=False)
        downloader.__enter__ = Mock(return_value=downloader)
        downloader.__exit__ = Mock(return_value=False)
        with patch.object(self.worker, 'options', return_value={'download_archive': {'youtube 1'}}), patch('engine.YoutubeDL', factory):
            self.worker.run()
        events = list(self.events.queue)
        counts = [v for kind, v in events if kind == 'overall']
        self.assertEqual(counts[-1]['total'], 4)
        self.assertEqual(counts[-1]['processed'], 4)
        self.assertEqual((counts[-1]['saved'], counts[-1]['skipped'], counts[-1]['errors']), (2, 1, 1))
        self.assertEqual([v['processed'] for v in counts if v['total'] == 4], [0, 0, 1, 1, 2, 2, 3, 3, 4])
        result = events[-1][1]
        self.assertEqual((result['completed'], result['skipped'], result['track_errors']), (2, 1, 1))
        self.assertEqual(result['failed'], [job])
        self.assertIsNone(factory.call_args_list[0].args[0]['download_archive'])

    def test_playlist_scan_failure_does_not_report_empty_success(self):
        self.worker.jobs = [dict(id='p', url='https://youtube.com/playlist?list=test', playlist=True)]
        with patch.object(self.worker, 'options', return_value={}), patch('engine.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = None
            self.worker.run()
        result = list(self.events.queue)[-1][1]
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['completed'], 0)

    def test_unknown_file_size_is_not_reported_as_zero_percent(self):
        self.worker.progress({'status': 'downloading', 'downloaded_bytes': 1000})
        progress = [v for kind, v in self.events.queue if kind == 'progress'][-1]
        self.assertIsNone(progress['fraction'])
        self.assertEqual(progress['downloaded'], 1000)

    def test_stop_during_processing_keeps_current_track_unfinished(self):
        job = dict(id='video', url='https://youtu.be/abcdefghijk', playlist=False)
        self.worker.jobs = [job]
        with patch.object(self.worker, 'options', return_value={}), patch('engine.YoutubeDL') as factory:
            downloader = factory.return_value.__enter__.return_value
            downloader.in_download_archive.return_value = False
            def download(*a, **k):
                self.worker.progress({'status': 'finished'})
                self.worker.stop.set()
                Completed(self.worker).run({'title': 'Track'})
            downloader.extract_info.side_effect = download
            self.worker.run()
        result = list(self.events.queue)[-1][1]
        self.assertTrue(result['stopped'])
        self.assertEqual(result['completed'], 0)
        self.assertEqual(self.worker.tally['processed'], 0)

    def test_new_queue_link_resets_playlist_counts(self):
        self.worker.jobs = [dict(id=str(i), url=f'https://youtu.be/{i:011}', playlist=False) for i in range(2)]
        with patch.object(self.worker, 'options', return_value={}), patch('engine.YoutubeDL') as factory:
            downloader = factory.return_value.__enter__.return_value
            downloader.in_download_archive.return_value = True
            self.worker.run()
        starts = [v for kind, v in self.events.queue if kind == 'overall' and v['total'] is None]
        self.assertEqual([v['job_index'] for v in starts], [1, 2])
        self.assertTrue(all(v['processed'] == v['skipped'] == 0 for v in starts))
        self.assertEqual(list(self.events.queue)[-1][1]['skipped'], 2)

    def test_directory_failure_is_reported(self):
        file = Path(self.directory.name) / 'not-a-directory'
        file.write_text('test')
        self.worker.settings['folder'] = str(file)
        self.worker.run()
        self.assertEqual(list(self.events.queue)[-1][1]['errors'], 1)


if __name__ == '__main__':
    unittest.main()
