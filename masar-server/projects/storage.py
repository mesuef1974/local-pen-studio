"""The only module that touches asset bytes, so a deployment can swap the storage."""
import os
import tempfile
from pathlib import Path

from django.conf import settings


def _path(sha256):
    # sha256 is always a digest computed or validated by this server, never a user path.
    return Path(settings.FILES_DIR) / sha256[:2] / sha256


def write(sha256, data):
    path = _path(sha256)
    if path.is_file() and path.stat().st_size == len(data):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix='.part')
    try:
        with os.fdopen(handle, 'wb') as file:
            file.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def open_for_read(sha256):
    return _path(sha256).open('rb')
