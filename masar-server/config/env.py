"""Read configuration from the environment, with an optional local .env file."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / '.env'


def load_env_file(path=ENV_FILE):
    """Load KEY=VALUE lines; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())
