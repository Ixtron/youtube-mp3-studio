import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('audit_publish', Path(__file__).resolve().parents[1] / 'scripts/audit_publish.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, capture_output=True, check=True)

    def stage(self, name, content):
        (self.root / name).write_text(content, encoding='utf-8')
        self.git('add', '--', name)

    def audit(self):
        with patch.object(audit, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()) as output:
            result = audit.main()
        return result, output.getvalue()

    def test_cookie_file_is_blocked_even_without_recognizable_contents(self):
        self.stage('youtube_cookies.txt', 'FAKE TEST DATA')
        self.assertEqual(self.audit()[0], 1)

    def test_staged_secret_cannot_be_hidden_by_clean_working_copy(self):
        token = 'gh' + 'p_' + 'A' * 36
        self.stage('app.py', 'token = ' + repr(token))
        (self.root / 'app.py').write_text('# clean working copy')
        result, output = self.audit()
        self.assertEqual(result, 1)
        self.assertNotIn(token, output)

    def test_existing_committed_file_is_still_scanned(self):
        self.stage('unexpected.txt', 'FAKE TEST DATA')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Test')
        self.stage('app.py', '# safe')
        self.assertEqual(self.audit()[0], 1)

    def test_clean_source_is_accepted(self):
        self.stage('app.py', '# safe')
        self.assertEqual(self.audit()[0], 0)
