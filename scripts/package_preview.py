"""Create a local preview ZIP from an explicitly checked bundle. Never uploads."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'dist' / 'YouTubeMP3'
OUTPUT = ROOT / 'release'
ZAPRET_HASH = '291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34'
EXECUTABLES = {'YouTubeMP3.exe', 'LoginHelper.exe', 'ffmpeg.exe', 'ffprobe.exe', 'node.exe'}


def sha256(file):
    with file.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    for name in EXECUTABLES:
        if not (BUNDLE / name).is_file():
            raise RuntimeError('Missing component: ' + name)
    original = ROOT / 'vendor' / 'zapret-1.10.4.zip'
    if sha256(original) != ZAPRET_HASH:
        raise RuntimeError('Unverified Zapret archive')
    with zipfile.ZipFile(original) as archive:
        expected = {}
        for item in archive.infolist():
            if not item.is_dir():
                name = '/'.join(Path(item.filename).parts[1:])
                expected[name] = hashlib.sha256(archive.read(item)).hexdigest()
        actual = {file.relative_to(BUNDLE / 'zapret').as_posix(): sha256(file)
                  for file in (BUNDLE / 'zapret').rglob('*') if file.is_file()}
        if actual != expected:
            raise RuntimeError('Bundled Zapret differs from the official archive. No package was created.')
    files = sorted(file for file in BUNDLE.rglob('*') if file.is_file())
    for file in files:
        relative = file.relative_to(BUNDLE)
        if relative.parts[0] not in EXECUTABLES | {'_internal', 'zapret', 'licenses'}:
            raise RuntimeError('Unexpected top-level bundle file: ' + relative.as_posix())
        # Runtime browser data never belongs in a portable release.
        if any(part.lower() in {'ebwebview', 'user data', 'browser-profile', 'local storage',
                                'session storage', 'youtube_cookies.txt', 'settings.json'} for part in relative.parts):
            raise RuntimeError('Private runtime data in bundle: ' + relative.as_posix())
        if file.suffix.lower() in {'.log', '.mp3', '.m4a', '.webm', '.part'}:
            raise RuntimeError('Unexpected media/log in bundle: ' + relative.as_posix())
    OUTPUT.mkdir(exist_ok=True)
    target = OUTPUT / 'YouTubeMP3-windows-x64-preview.zip'
    manifest = {'status': 'local-preview', 'files': []}
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            relative = file.relative_to(BUNDLE).as_posix()
            archive.write(file, relative)
            manifest['files'].append({'path': relative, 'sha256': sha256(file), 'size': file.stat().st_size})
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP verification failed')
    (OUTPUT / 'preview-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    digest = sha256(target)
    (OUTPUT / 'SHA256SUMS-preview.txt').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print(f'Preview created and ZIP CRC verified: {len(files)} files, {target.stat().st_size / 1048576:.1f} MiB')
    print('SHA256: ' + digest)


if __name__ == '__main__':
    main()
