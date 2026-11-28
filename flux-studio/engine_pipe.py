"""The FLUX service process and its line protocol, shared by the studio and the Masar job worker.

Standard library only: the account server's environment has no imaging or model packages.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT.parent))
from process_guard import terminate_tree  # noqa: E402

# The environment lives beside the app; only the interpreter's place inside it depends on the system.
PYTHON = ROOT / '.venv-flux' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
SERVICE = ROOT / 'generation_service.py'


def keep_warm_seconds():
    """Idle seconds the loaded model is kept after a job; 0 restores one process per job."""
    try:
        value = float(os.environ.get('FLUX_KEEP_WARM_S', '300'))
    except ValueError:
        return 300.0
    return value if math.isfinite(value) and 0 <= value <= 3600 else 300.0


# The studio and the job worker are separate processes with one graphics card between them.
CARD_DIR = Path(os.environ.get('MASAR_GPU_DIR') or tempfile.gettempdir())
WANTED_SECONDS = 60


class Card:
    """A lock file: whoever holds it may load a model. The system drops it if the holder dies."""

    def __init__(self, folder=None):
        folder = Path(folder or CARD_DIR)
        self.path = folder / 'masar-gpu.lock'
        self.wanted_path = folder / 'masar-gpu.wanted'
        self.file = None

    def acquire(self):
        if self.file:
            return True
        file = open(self.path, 'a+b')
        try:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self.file = file
        return True

    def release(self):
        file, self.file = self.file, None
        if file:
            if os.name == 'nt':
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            file.close()  # closing also drops a flock

    def wanted(self):
        """Another process is waiting: an idle holder should unload and let go."""
        try:
            return time.time() - self.wanted_path.stat().st_mtime < WANTED_SECONDS
        except OSError:
            return False

    def borrow(self, timeout):
        """Ask an idle holder to let go, and wait for it. False while it is still working."""
        self.wanted_path.touch()
        deadline = time.monotonic() + timeout
        try:
            while not self.acquire():
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.2)
            return True
        finally:
            self.wanted_path.unlink(missing_ok=True)


def spawn(command, log_path, cancel_file):
    """Start a service process. Returns it with the open log that receives its stderr."""
    # Stderr is diagnostic-only, kept outside HTTP responses and user images.
    try:
        log_path.replace(log_path.with_suffix('.previous.log'))  # keep the last crash trace
    except OSError:
        pass
    log = log_path.open('w', encoding='utf-8')
    try:
        process = subprocess.Popen([str(part) for part in command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=log, text=True, encoding='utf-8',
                                   env=os.environ | {'FLUX_CANCEL_FILE': str(cancel_file)},
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except BaseException:
        log.close()
        raise
    return process, log


def send(process, message, keep_warm):
    process.stdin.write(json.dumps(message) + '\n')
    process.stdin.flush()
    if not keep_warm:
        process.stdin.close()


def read_reply(process, on_event):
    """Read one job's events. Returns (result, error text, whether the process can serve another)."""
    result = failure = None
    done = False
    for line in iter(process.stdout.readline, ''):
        try:
            event = json.loads(line)
        except ValueError:
            continue  # a library printed to stdout; not a protocol event
        if not isinstance(event, dict):
            continue
        if event.get('state') in ('loading', 'running'):
            on_event(event)
        if 'result' in event:
            result = event['result']
        if 'error' in event:
            failure = event['error']
        if event.get('done'):
            done = not event.get('exiting')  # a worker that announced its exit is not kept
            break
    return result, failure, done


def stop(process, log):
    """End the process; the driver returns its VRAM once it has exited."""
    if process:
        try:
            process.stdin.close()  # EOF is the service's normal exit signal
        except OSError:
            pass
        try:
            process.wait(timeout=5 if process.poll() is None else 0)
        except subprocess.TimeoutExpired:
            terminate_tree(process)
            process.wait()
        if process.stdout:
            process.stdout.close()
    if log:
        log.close()
