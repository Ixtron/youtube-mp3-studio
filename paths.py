"""Application resources and private, per-user state are deliberately separate."""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'YouTubeMP3' / 'data'
COOKIES = DATA / 'youtube_cookies.txt'
DEFAULT_DOWNLOADS = Path.home() / 'Music' / 'YouTubeMP3'


def binary(name):
    for folder in (ROOT, ROOT / 'vendor'):
        candidate = folder / (name + '.exe')
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def read_settings():
    try:
        value = json.loads((DATA / 'settings.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(value):
    DATA.mkdir(parents=True, exist_ok=True)
    temporary = DATA / 'settings.tmp'
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(DATA / 'settings.json')
