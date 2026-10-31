import unittest
from unittest.mock import Mock, patch
import customtkinter as ctk
from app import App


class AppTests(unittest.TestCase):
    def test_queue_and_shutdown_do_not_unlock_running_worker(self):
        with patch('app.read_settings', return_value={}):
            ctk.set_appearance_mode('dark')
            app = App()
        try:
            app.withdraw()
            app.urls.insert('1.0', 'https://youtu.be/abcdefghijk\nhttps://youtu.be/abcdefghijk')
            app.add_urls()
            self.assertEqual(len(app.jobs), 1)
            app.thread = Mock()
            app.thread.is_alive.return_value = True
            app.worker = Mock()
            app.set_busy(True)
            app.stop()
            self.assertEqual(app.start_button.cget('state'), 'disabled')
            app.clear_jobs()
            self.assertEqual(len(app.jobs), 1)
            app.thread.is_alive.return_value = False
            app.finish(dict(completed=0, errors=1, stopped=False, failed=app.jobs[:]))
            self.assertIn('ошибками', app.status.cget('text'))
            self.assertEqual(app.retry_button.cget('state'), 'normal')
        finally:
            app.destroy()


if __name__ == '__main__':
    unittest.main()
