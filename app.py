"""YouTube MP3 / desktop edition."""
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from engine import Worker, validate_url, playlist_url
from paths import ROOT, DATA, COOKIES, DEFAULT_DOWNLOADS, binary, read_settings, save_settings

BG = '#0C111B'
CARD = '#151D2C'
FIELD = '#0F1623'
LINE = '#283449'
MUTED = '#98A7BE'
TEXT = '#EDF3FC'
ACCENT = '#58D6B0'


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('YouTube MP3 — Studio')
        self.geometry(f'1180x{min(850, self.winfo_screenheight() - 100)}+20+20')
        self.minsize(1000, 720)
        self.configure(fg_color=BG)
        self.events = queue.Queue()
        self.jobs, self.rows, self.failed = [], {}, []
        self.worker = self.thread = self.login_process = None
        self.saved = read_settings()
        self.build()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def label(self, parent, text, size=14, color=TEXT, bold=False, **kw):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=ctk.CTkFont('Segoe UI', size, weight='bold' if bold else 'normal'), **kw)

    def button(self, parent, text, command, primary=False, **kw):
        return ctk.CTkButton(parent, text=text, command=command, height=40, corner_radius=10,
                            font=ctk.CTkFont('Segoe UI', 13, weight='bold'),
                            fg_color=ACCENT if primary else '#243149',
                            hover_color='#7FE6C6' if primary else '#34445E',
                            text_color=BG if primary else TEXT, **kw)

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, minsize=290)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, columnspan=2, sticky='ew', padx=28, pady=(24, 20))
        self.label(header, '◉', 38, ACCENT).pack(side='left', padx=(0, 14))
        titles = ctk.CTkFrame(header, fg_color='transparent')
        titles.pack(side='left')
        self.label(titles, 'YouTube MP3', 25, bold=True, anchor='w').pack(anchor='w')
        self.label(titles, 'Твоя музыка. В твоей библиотеке.', 13, MUTED).pack(anchor='w')
        self.label(header, 'STUDIO  /  4.0 preview', 12, MUTED).pack(side='right')

        main = ctk.CTkFrame(self, fg_color='transparent')
        main.grid(row=1, column=0, sticky='nsew', padx=(28, 18), pady=(0, 20))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)
        source = ctk.CTkFrame(main, fg_color=CARD, corner_radius=18)
        source.grid(row=0, column=0, sticky='ew')
        self.label(source, 'Что будем слушать?', 22, bold=True).pack(anchor='w', padx=22, pady=(18, 2))
        self.label(source, 'Добавь ссылки на видео или плейлисты — по одной на строку.', 13, MUTED).pack(anchor='w', padx=22)
        self.urls = ctk.CTkTextbox(source, height=84, fg_color=FIELD, border_color=LINE,
                                  border_width=1, corner_radius=10, font=('Segoe UI', 14))
        self.urls.pack(fill='x', padx=22, pady=14)
        controls = ctk.CTkFrame(source, fg_color='transparent')
        controls.pack(fill='x', padx=22, pady=(0, 18))
        self.button(controls, 'Вставить', self.paste, width=95).pack(side='left')
        self.mode = ctk.StringVar(value='Авто')
        ctk.CTkOptionMenu(controls, values=['Авто', 'Одно видео', 'Плейлист'], variable=self.mode,
                         fg_color=FIELD, button_color=LINE, height=40, width=120).pack(side='left', padx=10)
        self.add_button = self.button(controls, '+ В очередь', self.add_urls, primary=True, width=145)
        self.add_button.pack(side='right')

        queue_header = ctk.CTkFrame(main, fg_color='transparent')
        queue_header.grid(row=1, column=0, sticky='ew', pady=(18, 8))
        self.count = self.label(queue_header, 'Очередь  ·  0', 16, bold=True)
        self.count.pack(side='left')
        self.clear_button = self.button(queue_header, 'Очистить', self.clear_jobs, width=90)
        self.clear_button.pack(side='right')
        self.queue_view = ctk.CTkScrollableFrame(main, fg_color=CARD, corner_radius=14, height=160)
        self.queue_view.grid(row=2, column=0, sticky='nsew')
        self.empty = self.label(self.queue_view, 'Здесь появится твоя следующая подборка.\nДобавь первую ссылку выше.', 15, MUTED)
        self.empty.pack(pady=35)

        progress = ctk.CTkFrame(main, fg_color=CARD, corner_radius=14)
        progress.grid(row=3, column=0, sticky='ew', pady=(14, 0))
        self.status = self.label(progress, 'Готов к загрузке', 15, bold=True, anchor='w')
        self.status.pack(fill='x', padx=18, pady=(12, 3))
        self.detail = self.label(progress, 'Выбери музыку — остальное сделаем за тебя.', 12, MUTED, anchor='w')
        self.detail.pack(fill='x', padx=18)
        self.bar = ctk.CTkProgressBar(progress, progress_color=ACCENT, fg_color=LINE, height=6)
        self.bar.pack(fill='x', padx=18, pady=12)
        self.bar.set(0)
        actions = ctk.CTkFrame(progress, fg_color='transparent')
        actions.pack(fill='x', padx=18, pady=(0, 14))
        self.start_button = self.button(actions, 'Начать загрузку', self.start, primary=True, width=160)
        self.start_button.pack(side='left')
        self.pause_button = self.button(actions, 'Пауза', self.pause, width=90, state='disabled')
        self.pause_button.pack(side='left', padx=8)
        self.stop_button = self.button(actions, 'Стоп', self.stop, width=80, state='disabled')
        self.stop_button.pack(side='left')
        self.retry_button = self.button(actions, 'Повторить ошибки', self.retry, width=145, state='disabled')
        self.retry_button.pack(side='right')
        self.log = ctk.CTkTextbox(main, height=88, fg_color=BG, text_color=MUTED, font=('Consolas', 11))
        self.log.grid(row=4, column=0, sticky='ew', pady=(8, 0))
        self.log.configure(state='disabled')

        side = ctk.CTkScrollableFrame(self, width=270, fg_color=CARD, corner_radius=18)
        self.settings_panel = side
        side.grid(row=1, column=1, sticky='nsew', padx=(0, 28), pady=(0, 20))
        self.label(side, 'Как сохранить', 20, bold=True).pack(anchor='w', padx=14, pady=(14, 18))
        self.label(side, 'ФОРМАТ АУДИО', 11, MUTED, True).pack(anchor='w', padx=14)
        self.format = ctk.StringVar(value=self.saved.get('format_label', 'MP3'))
        ctk.CTkSegmentedButton(side, values=['MP3', 'M4A', 'Исходный'], variable=self.format,
                               selected_color='#287C67', selected_hover_color='#34987E', height=36).pack(fill='x', padx=14, pady=(8, 16))
        self.label(side, 'Качество MP3', 13, MUTED).pack(anchor='w', padx=14)
        self.quality = ctk.StringVar(value=self.saved.get('quality', '320'))
        ctk.CTkOptionMenu(side, values=['320', '256', '192', '128'], variable=self.quality,
                         fg_color=FIELD, button_color=LINE, height=36).pack(fill='x', padx=14, pady=(6, 6))
        self.label(side, 'Битрейт не улучшает качество источника.', 11, MUTED).pack(anchor='w', padx=14)
        self.thumbnail = ctk.BooleanVar(value=self.saved.get('thumbnail', True))
        ctk.CTkSwitch(side, text='Добавить обложку', variable=self.thumbnail,
                      progress_color='#287C67').pack(anchor='w', padx=14, pady=18)
        self.label(side, 'ПАПКА БИБЛИОТЕКИ', 11, MUTED, True).pack(anchor='w', padx=14, pady=(5, 8))
        self.folder = ctk.StringVar(value=self.saved.get('folder', str(DEFAULT_DOWNLOADS)))
        ctk.CTkEntry(side, textvariable=self.folder, height=36, fg_color=FIELD, border_color=LINE).pack(fill='x', padx=14)
        self.button(side, 'Выбрать папку', self.choose_folder).pack(fill='x', padx=14, pady=(8, 6))
        self.button(side, 'Открыть библиотеку', self.open_folder).pack(fill='x', padx=14, pady=(0, 20))
        self.label(side, 'ДОСТУП К YOUTUBE', 11, MUTED, True).pack(anchor='w', padx=14)
        self.cookies = ctk.StringVar(value='Без входа')
        ctk.CTkOptionMenu(side, values=['Без входа', 'Сохранённый вход', 'Chrome', 'Edge', 'Firefox', 'Opera'],
                         variable=self.cookies, fg_color=FIELD, button_color=LINE, height=36).pack(fill='x', padx=14, pady=8)
        self.login_button = self.button(side, 'Войти в YouTube', self.login)
        self.login_button.pack(fill='x', padx=14, pady=(0, 6))
        self.button(side, 'Удалить сохранённый вход', self.logout).pack(fill='x', padx=14)
        self.auth = self.label(side, 'Вход сохранён локально' if COOKIES.exists() else 'Вход нужен только для части видео.', 11, MUTED)
        self.auth.pack(anchor='w', padx=14, pady=8)
        self.label(side, 'Пауза между треками', 13, MUTED).pack(anchor='w', padx=14, pady=(12, 6))
        self.delay = ctk.StringVar(value=str(self.saved.get('delay', 3)))
        ctk.CTkOptionMenu(side, values=['0', '1', '3', '5'], variable=self.delay,
                         fg_color=FIELD, button_color=LINE, height=36).pack(fill='x', padx=14)
        self.label(side, 'Секунды + случайная задержка до 3 с.', 11, MUTED).pack(anchor='w', padx=14, pady=6)
        self.label(side, 'Личные данные остаются\nв профиле Windows.', 12, MUTED, justify='left').pack(anchor='w', padx=14, pady=(20, 12))
        self.label(side, 'ПОДКЛЮЧЕНИЕ', 11, MUTED, True).pack(anchor='w', padx=14, pady=(14, 8))
        self.network_profile = ctk.StringVar(value='general (ALT).bat')
        network_root = self.network_directory()
        profiles = sorted(path.name for path in network_root.glob('general*.bat')) if network_root else ['general (ALT).bat']
        ctk.CTkOptionMenu(side, values=profiles, variable=self.network_profile, fg_color=FIELD,
                         button_color=LINE, height=36).pack(fill='x', padx=14, pady=(0, 8))
        self.button(side, 'Включить Zapret', self.launch_network_helper).pack(fill='x', padx=14, pady=(0, 6))
        self.label(side, 'Встроенная версия 1.10.4 · запрос UAC.\nДля остановки закрой окно zapret.', 11, MUTED, justify='left').pack(anchor='w', padx=14, pady=(0, 14))
        self.after(250, lambda: side._parent_canvas.yview_moveto(0))

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def paste(self):
        try:
            self.urls.insert('end', self.clipboard_get().strip() + '\n')
        except Exception:
            self.write_log('Буфер обмена не содержит текста.')

    def add_urls(self):
        urls = list(dict.fromkeys(self.urls.get('1.0', 'end').split()))
        if not urls:
            return True
        if any(not validate_url(url) for url in urls):
            messagebox.showerror('Проверь ссылки', 'Нужны полные ссылки https:// на YouTube или youtu.be.')
            return False
        for url in urls:
            if any(job['url'] == url for job in self.jobs):
                continue
            job = {'id': uuid.uuid4().hex, 'url': url,
                   'playlist': self.mode.get() == 'Плейлист' or (self.mode.get() == 'Авто' and playlist_url(url))}
            self.jobs.append(job)
            self.empty.pack_forget()
            row = ctk.CTkFrame(self.queue_view, fg_color=FIELD, corner_radius=10)
            row.pack(fill='x', padx=4, pady=4)
            self.label(row, '♫', 23, ACCENT).pack(side='left', padx=12)
            content = ctk.CTkFrame(row, fg_color='transparent')
            content.pack(side='left', fill='x', expand=True, pady=9)
            self.label(content, url if len(url) < 65 else url[:62] + '…', 12, anchor='w').pack(fill='x')
            status = self.label(content, 'Плейлист · В очереди' if job['playlist'] else 'Видео · В очереди', 11, MUTED, anchor='w')
            status.pack(fill='x')
            self.rows[job['id']] = (row, status)
        self.urls.delete('1.0', 'end')
        self.count.configure(text=f'Очередь  ·  {len(self.jobs)}')
        return True

    def clear_jobs(self):
        if self.thread and self.thread.is_alive():
            return
        for row, _ in self.rows.values():
            row.destroy()
        self.jobs, self.rows, self.failed = [], {}, []
        self.empty.pack(pady=35)
        self.count.configure(text='Очередь  ·  0')
        self.retry_button.configure(state='disabled')

    def settings(self):
        return {'folder': self.folder.get().strip() or str(DEFAULT_DOWNLOADS),
                'format_label': self.format.get(), 'format': {'MP3': 'mp3', 'M4A': 'm4a', 'Исходный': 'original'}[self.format.get()],
                'quality': self.quality.get(), 'thumbnail': self.thumbnail.get(), 'delay': int(self.delay.get()),
                'cookies': {'Без входа': 'none', 'Сохранённый вход': 'saved'}.get(self.cookies.get(), self.cookies.get().lower())}

    def start(self, jobs=None):
        if self.thread and self.thread.is_alive():
            return
        if jobs is None:
            if not self.add_urls():
                return
            jobs = self.jobs
        if not jobs:
            return
        missing = [name for name in ('ffmpeg', 'ffprobe', 'node') if not binary(name)]
        if missing:
            messagebox.showerror('Не хватает компонентов', 'Не найдены: ' + ', '.join(missing) + '\nПомести их в папку vendor или добавь в PATH.')
            return
        settings = self.settings()
        try:
            save_settings({key: value for key, value in settings.items() if key != 'cookies'})
        except OSError as error:
            messagebox.showerror('Настройки', str(error))
            return
        self.worker = Worker(list(jobs), settings, self.events)
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.failed = []
        self.set_busy(True)
        self.bar.set(0)
        self.thread.start()

    def set_busy(self, busy):
        for button in (self.start_button, self.add_button, self.clear_button):
            button.configure(state='disabled' if busy else 'normal')
        self.pause_button.configure(state='normal' if busy else 'disabled', text='Пауза')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.retry_button.configure(state='normal' if self.failed and not busy else 'disabled')

    def pause(self):
        if self.worker.resume.is_set():
            self.worker.resume.clear()
            self.pause_button.configure(text='Продолжить')
            self.status.configure(text='Пауза при ближайшем шаге загрузки')
        else:
            self.worker.resume.set()
            self.pause_button.configure(text='Пауза')

    def stop(self):
        if self.worker:
            self.worker.stop.set()
            self.worker.resume.set()
            self.status.configure(text='Остановка… ожидаем завершения текущего шага')
            self.stop_button.configure(state='disabled')
            self.pause_button.configure(state='disabled')

    def retry(self):
        self.start(list(self.failed))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.write_log(value)
                elif kind == 'job' and value[0] in self.rows:
                    self.rows[value[0]][1].configure(text=value[1])
                elif kind == 'status':
                    if self.worker and not self.worker.stop.is_set():
                        self.status.configure(text=value)
                elif kind == 'progress':
                    self.bar.set(min(1, max(0, value['fraction'])))
                    title = value['title']
                    self.detail.configure(text=(title[:62] + '…') if len(title) > 65 else title)
                    if self.worker.resume.is_set() and not self.worker.stop.is_set():
                        eta = f"{value['eta']} с" if value['eta'] is not None else '—'
                        self.status.configure(text=f"Загрузка · {value['fraction']:.0%}  /  {value['speed'] / 1048576:.1f} МБ/с  /  осталось {eta}")
                elif kind == 'track':
                    self.write_log('Сохранено: ' + value)
                elif kind == 'done':
                    self.finish(value)
                elif kind == 'login':
                    self.login_button.configure(state='normal')
                    if value:
                        self.write_log(value)
                    else:
                        self.cookies.set('Сохранённый вход')
                        self.auth.configure(text='Вход сохранён локально')
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def finish(self, result):
        # The queue message can arrive just before the worker thread returns.
        if self.thread and self.thread.is_alive():
            self.after(50, lambda: self.finish(result))
            return
        self.failed = result['failed']
        self.set_busy(False)
        title = 'Остановлено' if result['stopped'] else ('Завершено с ошибками' if result['errors'] else 'Готово')
        self.status.configure(text=f"{title} · сохранено треков: {result['completed']} · ошибок ссылок: {result['errors']}")
        if not result['errors'] and not result['stopped']:
            self.bar.set(1)

    def choose_folder(self):
        value = filedialog.askdirectory()
        if value:
            self.folder.set(value)

    def open_folder(self):
        folder = Path(self.folder.get().strip() or DEFAULT_DOWNLOADS)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as error:
            messagebox.showerror('Папка', str(error))

    def login(self):
        if self.login_process and self.login_process.poll() is None:
            return
        DATA.mkdir(parents=True, exist_ok=True)
        command = [str(ROOT / 'LoginHelper.exe')] if getattr(sys, 'frozen', False) else [sys.executable, str(ROOT / 'login_helper.py')]
        try:
            self.login_process = subprocess.Popen(command + [str(COOKIES)], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as error:
            self.write_log('Не удалось открыть вход: ' + str(error))
            return
        self.login_button.configure(state='disabled')
        def wait():
            output, error = self.login_process.communicate()
            ok = self.login_process.returncode == 0 and 'OK:' in output and COOKIES.is_file()
            self.events.put(('login', None if ok else 'Вход не завершён. Если встроенный браузер недоступен, выбери браузер в списке.'))
        threading.Thread(target=wait, daemon=True).start()

    def logout(self):
        if self.thread and self.thread.is_alive() or self.login_process and self.login_process.poll() is None:
            messagebox.showinfo('Вход используется', 'Сначала останови загрузку и закрой окно входа.')
            return
        try:
            COOKIES.unlink(missing_ok=True)
            self.cookies.set('Без входа')
            self.auth.configure(text='Сохранённый вход удалён')
        except OSError as error:
            self.write_log(str(error))

    @staticmethod
    def network_directory():
        for directory in (ROOT / 'zapret', ROOT / 'vendor' / 'zapret' / 'zapret-discord-youtube-1.10.4'):
            if (directory / 'service.bat').is_file():
                return directory
        return None

    def launch_network_helper(self):
        directory = self.network_directory()
        if directory is None:
            messagebox.showerror('Zapret', 'Встроенный компонент отсутствует. Восстанови полную сборку программы.')
            return
        profiles = {path.name: path for path in directory.glob('general*.bat')}
        profile = profiles.get(self.network_profile.get())
        if profile is None:
            return
        import ctypes
        result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', str(profile), None, str(directory), 1)
        self.write_log('Запрошен запуск встроенного Zapret. Для остановки закрой его окно.' if result > 32 else 'Запуск отменён или не удался.')

    def close(self):
        if self.thread and self.thread.is_alive():
            self.stop()
            messagebox.showinfo('Остановка загрузки', 'Дождись остановки, затем закрой окно. Так текущие файлы останутся целыми.')
            return
        if self.login_process and self.login_process.poll() is None:
            messagebox.showinfo('Окно входа', 'Сначала закрой окно входа в YouTube.')
            return
        try:
            save_settings({key: value for key, value in self.settings().items() if key != 'cookies'})
        except OSError:
            pass
        self.destroy()


if __name__ == '__main__':
    ctk.set_appearance_mode('dark')
    App().mainloop()
