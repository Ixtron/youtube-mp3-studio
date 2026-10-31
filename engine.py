"""Download worker. All UI communication goes through an event queue."""
import re
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.common import PostProcessor
from mutagen.id3 import ID3
from mutagen import MutagenError
from paths import binary, COOKIES


def validate_url(url):
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or '').lower()
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and (
        host == 'youtu.be' or host == 'youtube.com' or host.endswith('.youtube.com'))


def playlist_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.path == '/playlist' or ('list' in query and 'v' not in query)


class Cancelled(Exception):
    pass


def existing_video_id(file):
    match = re.search(r'\[([A-Za-z0-9_-]{11})\]$', file.stem)
    if match:
        return match.group(1)
    # Read old v3.x MP3 metadata without changing the user's files.
    if file.suffix.lower() == '.mp3':
        try:
            for frame in ID3(file).values():
                match = re.search(r'youtube\.com/watch\?v=([A-Za-z0-9_-]{11})', str(frame))
                if match:
                    return match.group(1)
        except (OSError, MutagenError):
            pass
    return None


class Completed(PostProcessor):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def run(self, info):
        self.worker.checkpoint()
        self.worker.completed += 1
        self.worker.emit('track', info.get('title', 'Аудио'))
        return [], info


class Worker:
    def __init__(self, jobs, settings, events):
        self.jobs, self.settings, self.events = jobs, settings, events
        self.stop = threading.Event()
        self.resume = threading.Event()
        self.resume.set()
        self.completed = 0
        self.errors = 0
        self.failed = []
        self.current_errors = 0

    def emit(self, kind, value):
        self.events.put((kind, value))

    def checkpoint(self):
        if self.stop.is_set():
            raise Cancelled('Остановлено')
        while not self.resume.wait(.15):
            if self.stop.is_set():
                raise Cancelled('Остановлено')

    def debug(self, message):
        pass

    def warning(self, message):
        self.emit('log', 'Предупреждение: ' + message)

    def error(self, message):
        self.current_errors += 1
        self.emit('log', re.sub(r'\x1b\[[0-9;]*m', '', message))

    def progress(self, data):
        self.checkpoint()
        if data['status'] == 'downloading':
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            self.emit('progress', {
                'fraction': data.get('downloaded_bytes', 0) / total if total else 0,
                'title': data.get('info_dict', {}).get('title', 'Загрузка'),
                'speed': data.get('speed') or 0, 'eta': data.get('eta'),
            })
        elif data['status'] == 'finished':
            self.emit('status', 'Обработка аудио…')

    def postprocess(self, data):
        self.checkpoint()
        if data['status'] == 'started':
            self.emit('status', 'Обработка аудио и метаданных…')

    def options(self):
        settings = self.settings
        folder = Path(settings['folder'])
        codec = settings['format']
        # A stable video ID prevents collisions and survives metadata changes.
        options = {
            'format': 'bestaudio/best',
            'outtmpl': str(folder / '%(title).180B [%(id)s].%(ext)s'),
            'windowsfilenames': True, 'overwrites': False,
            'continuedl': True, 'ignoreerrors': True,
            'quiet': True, 'logger': self,
            'ffmpeg_location': str(Path(binary('ffmpeg')).parent),
            'progress_hooks': [self.progress], 'postprocessor_hooks': [self.postprocess],
            'socket_timeout': 20, 'retries': 3, 'fragment_retries': 3,
            'sleep_interval': settings['delay'], 'max_sleep_interval': settings['delay'] + 3,
            'postprocessors': [],
        }
        if codec != 'original':
            options['postprocessors'].append({
                'key': 'FFmpegExtractAudio', 'preferredcodec': codec,
                'preferredquality': settings['quality'],
            })
        options['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
        if settings['thumbnail'] and codec != 'original':
            options['writethumbnail'] = True
            options['postprocessors'].append({'key': 'EmbedThumbnail'})
        node = binary('node')
        if node:
            options['js_runtimes'] = {'node': {'path': node}}
        browser = settings['cookies']
        if browser == 'saved':
            if not COOKIES.is_file():
                raise ValueError('Сначала войдите в аккаунт или выберите «Без входа».')
            options['cookiefile'] = str(COOKIES)
        elif browser != 'none':
            options['cookiesfrombrowser'] = (browser,)
        # Build the archive from real output files. A deleted track can be downloaded again.
        ids = set()
        extensions = {'mp3': {'.mp3'}, 'm4a': {'.m4a'},
                      'original': {'.webm', '.m4a', '.opus', '.ogg', '.mp3', '.mp4'}}[codec]
        for file in folder.iterdir():
            if file.is_file() and file.suffix.lower() in extensions and file.stat().st_size > 0:
                video_id = existing_video_id(file)
                if video_id:
                    ids.add('youtube ' + video_id)
        options['download_archive'] = ids
        return options

    def run(self):
        try:
            Path(self.settings['folder']).mkdir(parents=True, exist_ok=True)
            for index, job in enumerate(self.jobs):
                self.checkpoint()
                self.emit('job', (job['id'], 'Загрузка'))
                self.emit('status', f'Ссылка {index + 1} из {len(self.jobs)}')
                self.current_errors = 0
                before = self.completed
                try:
                    options = self.options()
                    options['noplaylist'] = not job['playlist']
                    with YoutubeDL(options) as downloader:
                        downloader.add_post_processor(Completed(self), when='after_move')
                        result = downloader.download([job['url']])
                    self.checkpoint()
                    if result or self.current_errors:
                        self.errors += 1
                        self.failed.append(job)
                        self.emit('job', (job['id'], 'Ошибка'))
                    else:
                        label = 'Готово' if self.completed > before else 'Уже скачано / нет доступных треков'
                        self.emit('job', (job['id'], label))
                except Cancelled:
                    self.emit('job', (job['id'], 'Остановлено'))
                    raise
                except Exception as error:
                    if self.stop.is_set():
                        self.emit('job', (job['id'], 'Остановлено'))
                        raise Cancelled() from error
                    self.errors += 1
                    self.failed.append(job)
                    self.emit('job', (job['id'], 'Ошибка'))
                    self.emit('log', str(error))
        except Cancelled:
            pass
        except Exception as error:
            self.errors += 1
            self.emit('log', str(error))
        finally:
            self.emit('done', {'completed': self.completed, 'errors': self.errors,
                               'stopped': self.stop.is_set(), 'failed': self.failed})
