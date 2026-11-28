import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from projects import backup


class Command(BaseCommand):
    help = 'Back up the database and asset files, then prove the backup restores.'

    def add_arguments(self, parser):
        parser.add_argument('--dest', default=os.environ.get('MASAR_BACKUP_DIR') or Path.home() / 'masar-backups')
        parser.add_argument('--verify-only', metavar='FOLDER', help='test an existing backup instead of making one')

    def handle(self, *args, dest, verify_only, **options):
        try:
            folder = verify_only
            if folder is None:
                folder, files = backup.create(dest)
                self.stdout.write(f'Backup: {folder} ({files} asset files)')
            counts, assets = backup.verify(folder)
        except (backup.BackupError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write('Restored rows: ' + ', '.join(f'{table}={count}' for table, count in counts.items()))
        self.stdout.write(self.style.SUCCESS(f'Restore test passed; {assets} asset files match.'))
