"""Fail closed: audit exactly the source files staged for Git publication.

Never prints matching secrets, only file names and reasons.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    '.gitignore', 'README.md', 'requirements.txt', 'app.py', 'engine.py', 'paths.py',
    'login_helper.py', 'install.ps1', 'scripts/build.ps1', 'scripts/audit_publish.py',
    'tests/test_engine.py', 'tests/test_app.py', 'tests/test_installer.ps1',
    '.github/workflows/check.yml',
    'scripts/fetch_zapret.ps1',
    'tests/test_publish.py',
    'scripts/package_preview.py', 'QA.md',
    '.github/workflows/release.yml', 'scripts/package_release.py', 'RELEASE_NOTES.md', 'LICENSE',
    'release.json',
}
PATTERNS = [
    rb'gh[pousr]_[A-Za-z0-9]{20,}', rb'github_pat_[A-Za-z0-9_]{20,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'(?m)^[^\r\n#]+\t(?:TRUE|FALSE)\t[^\r\n]+\t(?:TRUE|FALSE)\t\d+\t[^\r\n]+\t[^\r\n]+$',
    rb'C:' + rb'\\Users\\[^\\\s]+\\', rb'C:' + rb'/Users/[^/\s]+/',
]


def main():
    result = subprocess.run(['git', 'ls-files', '--cached', '-z'],
                            cwd=ROOT, capture_output=True, check=True)
    files = [value.decode('utf-8') for value in result.stdout.split(b'\0') if value]
    if not files:
        print('No indexed files. Nothing to publish.')
        return 1
    failures = []
    for name in files:
        if name not in ALLOWED:
            failures.append((name, 'not in reviewed source allowlist'))
            continue
        # Inspect the exact index content, not a potentially different working copy.
        data = subprocess.run(['git', 'show', ':' + name], cwd=ROOT, capture_output=True, check=True).stdout
        if len(data) > 250_000:
            failures.append((name, 'unexpectedly large source file'))
        if any(re.search(pattern, data) for pattern in PATTERNS):
            failures.append((name, 'possible credential or private local path'))
    for name, reason in failures:
        print(f'BLOCKED: {name}: {reason}')
    if failures:
        return 1
    print(f'PASS: {len(files)} indexed source files; allowlist and credential-pattern checks passed.')
    print('No binaries, downloaded media, browser profiles, logs or cookies are staged.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
