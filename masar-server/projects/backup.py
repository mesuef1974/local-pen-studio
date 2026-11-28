"""Back up the database and the asset files together, and prove a backup can be restored.

A backup is a folder: db.dump, files/<2>/<sha256>, manifest.json. Nothing here deletes a backup.
The restore test runs a private PostgreSQL server in a temporary folder, so it needs no extra
privilege and never writes to the real database.
"""
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings

DEFAULT_PG_BIN = r'C:\Program Files\PostgreSQL\17\bin'
SHA_QUERY = 'SELECT DISTINCT sha256 FROM projects_asset'
COUNTED = ('accounts_user', 'projects_project', 'projects_asset', 'projects_imageversion', 'projects_approval',
           'jobs_job', 'audit_auditevent')


class BackupError(RuntimeError):
    pass


def _tool(name):
    folder = Path(os.environ.get('MASAR_PG_BIN', DEFAULT_PG_BIN))
    found = shutil.which(name, path=str(folder)) or shutil.which(name)
    if found is None:
        raise BackupError(f'{name} not found. Set MASAR_PG_BIN to the PostgreSQL bin folder.')
    return found


def _run(command, password, *, quiet=False):
    # The password goes through the environment: command lines are visible to other processes.
    env = {**os.environ, 'PGPASSWORD': password, 'PGCONNECT_TIMEOUT': '10'}
    # quiet: a started server inherits the pipes, and waiting on them would never end.
    output = subprocess.DEVNULL if quiet else subprocess.PIPE
    result = subprocess.run(command, env=env, stdout=output, stderr=output, text=True, encoding='utf-8',
                            errors='replace')
    if result.returncode:
        raise BackupError(f'{Path(command[0]).stem} failed: {(result.stderr or "").strip()[-500:]}')
    return result.stdout


def _digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def copy_files(source, target):
    """Copy every stored asset. Assets are written once and never removed, so this may follow the dump."""
    count = 0
    for path in sorted(Path(source).glob('??/*')):
        if path.suffix == '.part':
            continue
        destination = target / path.parent.name / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        count += 1
    return count


def check_files(folder, hashes):
    """The hashes whose copy is missing or does not match its name."""
    bad = []
    for sha256 in hashes:
        path = Path(folder) / 'files' / sha256[:2] / sha256
        if not path.is_file() or _digest(path) != sha256:
            bad.append(sha256)
    return bad


def create(destination, now=None):
    database = settings.DATABASES['default']
    if not database['ENGINE'].endswith('postgresql'):
        raise BackupError('Only the PostgreSQL database can be backed up.')
    destination = Path(destination)
    final = destination / (now or datetime.now()).strftime('masar-%Y%m%d-%H%M%S')
    partial = final.with_name(final.name + '.partial')
    partial.mkdir(parents=True)
    dump = partial / 'db.dump'
    # Sessions are left out: a restored backup must not revive a signed-in browser.
    _run([_tool('pg_dump'), '-h', database['HOST'], '-p', str(database['PORT']), '-U', database['USER'],
          '-w', '-Fc', '--exclude-table-data=django_session', '-f', str(dump), database['NAME']],
         database['PASSWORD'])
    files = copy_files(settings.FILES_DIR, partial / 'files')
    manifest = {'created_at': datetime.now().astimezone().isoformat(), 'files': files, 'db_sha256': _digest(dump)}
    (partial / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Renamed only when complete: a folder without ".partial" is a whole backup.
    partial.rename(final)
    return final, files


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def verify(folder):
    """Restore into a throwaway server, then compare its asset rows with the copied files."""
    folder = Path(folder)
    dump, manifest = folder / 'db.dump', folder / 'manifest.json'
    if not dump.is_file() or not manifest.is_file():
        raise BackupError(f'{folder} is not a complete backup.')
    if _digest(dump) != json.loads(manifest.read_text(encoding='utf-8'))['db_sha256']:
        raise BackupError('db.dump changed since the backup was made.')
    with tempfile.TemporaryDirectory(prefix='masar-restore-', ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        data, password, port = root / 'data', secrets.token_urlsafe(24), str(_free_port())
        secret_file = root / 'pw'
        secret_file.write_text(password, encoding='ascii')
        _run([_tool('initdb'), '-D', str(data), '-U', 'restore', '-A', 'scram-sha-256', '-E', 'UTF8',
              '--no-locale', f'--pwfile={secret_file}'], password)
        secret_file.unlink()
        control = [_tool('pg_ctl'), '-D', str(data), '-w']
        _run([*control, '-l', str(root / 'server.log'), '-o', f'-p {port} -h 127.0.0.1', 'start'], password,
             quiet=True)
        try:
            connect = ['-h', '127.0.0.1', '-p', port, '-U', 'restore', '-w', '-d', 'postgres']
            _run([_tool('pg_restore'), *connect, '--exit-on-error', '--no-owner', '--no-privileges', str(dump)],
                 password)

            def query(sql):
                return _run([_tool('psql'), *connect, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', sql],
                            password).split()

            counts = {table: int(query(f'SELECT count(*) FROM {table}')[0]) for table in COUNTED}
            hashes = query(SHA_QUERY)
        finally:
            _run([*control, '-m', 'immediate', 'stop'], password, quiet=True)
    bad = check_files(folder, hashes)
    if bad:
        raise BackupError(f'{len(bad)} asset file(s) missing or damaged, first: {bad[0]}')
    return counts, len(hashes)
