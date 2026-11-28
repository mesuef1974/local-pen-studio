"""The parts that need no PostgreSQL server; the restore itself is run on the real machine."""
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from projects import backup

POSTGRES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'masar', 'USER': 'masar',
                        'PASSWORD': 'test-only', 'HOST': '127.0.0.1', 'PORT': '5432'}}


class BackupTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.sha = hashlib.sha256(b'picture').hexdigest()
        stored = self.root / 'files' / self.sha[:2]
        stored.mkdir(parents=True)
        (stored / self.sha).write_bytes(b'picture')
        (stored / 'half.part').write_bytes(b'x')

    def create(self, run):
        with override_settings(DATABASES=POSTGRES, FILES_DIR=self.root / 'files'), \
                mock.patch.object(backup, '_tool', lambda name: name), mock.patch.object(backup, '_run', run):
            return backup.create(self.root / 'out', datetime(2026, 1, 2, 3, 4, 5))

    def test_backup_holds_the_dump_and_every_whole_file(self):
        commands = []

        def dump(command, password, **options):
            commands.append(command)
            Path(command[command.index('-f') + 1]).write_bytes(b'dump')

        folder, files = self.create(dump)
        self.assertEqual((folder.name, files), ('masar-20260102-030405', 1))
        self.assertEqual(backup.check_files(folder, [self.sha]), [])
        self.assertFalse((folder / 'files' / self.sha[:2] / 'half.part').exists())
        self.assertNotIn('test-only', commands[0])
        (folder / 'files' / self.sha[:2] / self.sha).write_bytes(b'damaged')
        self.assertEqual(backup.check_files(folder, [self.sha]), [self.sha])
        (folder / 'db.dump').write_bytes(b'changed')
        with self.assertRaisesMessage(backup.BackupError, 'db.dump changed'):
            backup.verify(folder)

    def test_a_failed_dump_never_looks_complete(self):
        def fail(command, password, **options):
            raise backup.BackupError('pg_dump failed')

        with self.assertRaises(backup.BackupError):
            self.create(fail)
        self.assertEqual([path.name for path in (self.root / 'out').iterdir()], ['masar-20260102-030405.partial'])
