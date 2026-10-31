import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import customtkinter as ctk
from app import App


class AppTests(unittest.TestCase):
    @staticmethod
    def destroy_app(app):
        # CTk schedules timers beyond widget lifetime; cancel them between Tk roots.
        for timer in app.tk.call('after', 'info'):
            app.tk.call('after', 'cancel', timer)
        app.destroy()

    def make_app(self):
        with patch('app.read_settings', return_value={}):
            app = App()
        self.addCleanup(self.destroy_app, app)
        return app

    @unittest.skipUnless(sys.platform == 'win32', 'Windows virtual key codes')
    def test_paste_replaces_selection_once_in_both_keyboard_layouts(self):
        app = self.make_app()
        app.update()
        text = app.urls._textbox
        # Replace Tk's selection reader, leaving the user's clipboard untouched.
        app.tk.eval('rename ::tk::GetSelection ::tk::StudioOriginalSelection')
        app.tk.eval('proc ::tk::GetSelection {args} {return "https://youtu.be/abcdefghijk"}')
        try:
            for symbol in ('v', 'Cyrillic_em'):
                text.delete('1.0', 'end')
                text.insert('1.0', 'old text')
                text.tag_add('sel', '1.0', 'end-1c')
                event = SimpleNamespace(widget=text, keycode=0x56, keysym=symbol, state=4)
                self.assertEqual(app.edit_shortcut(event), 'break')
                self.assertEqual(text.get('1.0', 'end-1c'), 'https://youtu.be/abcdefghijk')
            # Exercise the actual binding chain too: the native class must not paste twice.
            text.delete('1.0', 'end')
            text.focus_force()
            app.update()
            text.event_generate('<Control-KeyPress>', keycode=0x56)
            self.assertEqual(text.get('1.0', 'end-1c'), 'https://youtu.be/abcdefghijk')
        finally:
            app.tk.eval('rename ::tk::GetSelection {}; rename ::tk::StudioOriginalSelection ::tk::GetSelection')

    def test_track_percentage_does_not_change_playlist_count(self):
        app = self.make_app()
        app.withdraw()
        app.show_overall(dict(job_id='p', job_index=1, jobs=1, playlist=True,
                              total=100, processed=7, saved=6, skipped=1, errors=0, current=8))
        app.events.put(('progress', dict(fraction=.45, downloaded=45, total=100,
                                        estimated=False, speed=1, eta=65)))
        app.poll()
        self.assertIn('7 из 100', app.overall.cget('text'))
        self.assertIn('Песня 8 из 100', app.status.cget('text'))
        self.assertIn('45%', app.status.cget('text'))
        self.assertAlmostEqual(app.overall_bar.get(), .07)
        self.assertAlmostEqual(app.bar.get(), .45)
        self.assertIn('1:05', app.transfer.cget('text'))

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
            self.destroy_app(app)


if __name__ == '__main__':
    unittest.main()
