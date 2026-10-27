"""Check tracked source without reading or printing possible secret values."""
import re
import subprocess
from pathlib import Path, PurePosixPath

MAX_BYTES = 10 * 1024 * 1024
BLOCKED_DIRS = {'models', 'node_modules', 'venv', '__pycache__', '.ssh', '.aws'}
BLOCKED_SUFFIXES = {'.safetensors', '.gguf', '.onnx', '.ckpt', '.pt', '.pth', '.bin',
                    '.pem', '.key', '.pfx', '.p12', '.log', '.pyc', '.sqlite', '.db'}
ACTION = re.compile(r'^\s*-?\s*uses:\s*([^\s#]+)', re.MULTILINE)


def path_error(name, size):
    path = PurePosixPath(name.lower())
    if any(part in BLOCKED_DIRS or part.startswith('.venv') for part in path.parts):
        return 'local environment, credentials directory or model directory'
    if path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example'):
        return 'environment secret file'
    if path.suffix in BLOCKED_SUFFIXES:
        return 'weights, credentials, logs or local state'
    if path.suffix == '.json' and path.name.startswith(('credentials', 'secrets')):
        return 'credential file'
    if size > MAX_BYTES:
        return 'file exceeds the 10 MiB source limit'
    return None


def workflow_errors(text):
    errors = []
    for action in ACTION.findall(text):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}', action):
            errors.append('external actions must be pinned to a full commit SHA')
    if re.search(r'^\s*pull_request_target\s*:', text, re.MULTILINE):
        errors.append('privileged pull_request_target requires a separate security review')
    return errors


def main():
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().strip('\0').split('\0')
    errors = []
    for name in filter(None, names):
        path = root / name
        error = path_error(name, path.stat().st_size)
        if error:
            errors.append(f'{name}: {error}')
        if name.startswith('.github/workflows/') and path.suffix in {'.yml', '.yaml'}:
            errors.extend(f'{name}: {error}' for error in workflow_errors(path.read_text(encoding='utf-8')))
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print(f'Repository policy passed for {len(names)} tracked files.')


if __name__ == '__main__':
    main()
