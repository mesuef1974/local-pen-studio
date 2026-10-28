"""Create a consistent SQLite backup of local Codex usage and coordination data."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import tempfile
from pathlib import Path


def backup(source: Path, destination_dir: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Database not found: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"usage-{stamp}.sqlite3"
    fd, temp_name = tempfile.mkstemp(prefix=".usage-backup-", suffix=".sqlite3.tmp", dir=destination_dir)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        original = sqlite3.connect(source, timeout=10)
        copy = sqlite3.connect(temporary)
        try:
            original.backup(copy)
            result = copy.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
        finally:
            original.close()
            copy.close()
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=codex_home / "usage-logs" / "usage.sqlite3")
    parser.add_argument("--destination", type=Path, default=codex_home / "usage-logs" / "backups")
    args = parser.parse_args()
    print(backup(args.database, args.destination))


if __name__ == "__main__":
    main()
