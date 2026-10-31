"""Package a clean CI build; large external tools are fetched by the installer."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'dist/YouTubeMP3'
OUTPUT = ROOT / 'release'


def main():
    # A CI build must contain only application files, never local runtime data.
    allowed = {'YouTubeMP3.exe', 'LoginHelper.exe', '_internal'}
    if {file.name for file in BUNDLE.iterdir()} - allowed:
        raise RuntimeError('Unexpected files in clean application build')
    licenses = BUNDLE / 'licenses'
    licenses.mkdir()
    notices = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        version = distribution.version
        notices.append(f'{name} {version}')
        destination = licenses / name
        for file in distribution.files or []:
            if any(word in file.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(file))
                if source.is_file() and source.suffix.lower() not in ('.py', '.pyc', '.exe', '.dll'):
                    destination.mkdir(exist_ok=True)
                    # Preserve distinct license paths without any machine-specific prefix.
                    target = destination / ('__'.join(part for part in file.parts if part not in ('..', '.')))
                    shutil.copyfile(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python license missing')
    shutil.copyfile(python_license, licenses / 'Python-LICENSE.txt')
    shutil.copyfile(ROOT / 'LICENSE', licenses / 'Application-GPL-3.0.txt')
    (licenses / 'COMPONENTS.txt').write_text('\n'.join(sorted(set(notices))) + '\n', encoding='utf-8')
    OUTPUT.mkdir(exist_ok=True)
    # mutagen is GPL-licensed; distribute the corresponding upstream source as well.
    version = metadata.version('mutagen')
    with urllib.request.urlopen(f'https://pypi.org/pypi/mutagen/{version}/json') as response:
        info = json.load(response)
    source = next(item for item in info['urls'] if item['packagetype'] == 'sdist')
    if not source['url'].startswith('https://files.pythonhosted.org/'):
        raise RuntimeError('Unexpected source distribution host')
    with urllib.request.urlopen(source['url']) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != source['digests']['sha256']:
        raise RuntimeError('Source distribution checksum mismatch')
    (OUTPUT / 'mutagen-source.tar.gz').write_bytes(data)
    archive_path = OUTPUT / 'YouTubeMP3-windows-x64.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(BUNDLE.rglob('*')):
            if file.is_file():
                relative = file.relative_to(BUNDLE)
                if any(part.lower() in {'ebwebview', 'browser-profile', 'user data'} for part in relative.parts):
                    raise RuntimeError('Browser profile in build')
                archive.write(file, relative.as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise RuntimeError('Archive verification failed')
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (OUTPUT / 'SHA256SUMS.txt').write_text(digest + '  ' + archive_path.name + '\n', encoding='ascii')
    print(f'Checked release archive: {archive_path.stat().st_size / 1048576:.1f} MiB')


if __name__ == '__main__':
    main()
