"""Dry-run-first retention for generated run folders (32-hex ids) under the apps' output roots.

Nothing is deleted unless --apply is passed. Only direct children whose name is a 32-character
hex id are ever considered, so source files and named folders are never touched.
"""
import argparse
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOTS = ('trace-studio/output', 'drawing-simulator/trace-output')
RUN_ID = re.compile(r'^[0-9a-f]{32}$')


def folder_size(path):
    return sum(item.stat().st_size for item in path.rglob('*') if item.is_file())


def stale_runs(base, days, now=None):
    """Return (path, age_days, size_bytes) for run folders last modified more than `days` ago."""
    now = time.time() if now is None else now
    found = []
    if not base.is_dir():
        return found
    for child in sorted(base.iterdir()):
        if child.is_symlink() or not child.is_dir() or not RUN_ID.match(child.name):
            continue
        age = (now - child.stat().st_mtime) / 86400
        if age > days:
            found.append((child, age, folder_size(child)))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30, help='keep runs newer than this many days (default 30)')
    parser.add_argument('--apply', action='store_true', help='actually delete; without it only a report is printed')
    parser.add_argument('--root', type=Path, default=ROOT, help='project root (for tests)')
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error('--days must be at least 1')
    total_count = 0
    total_bytes = 0
    for relative in OUTPUT_ROOTS:
        base = (args.root / relative).resolve()
        runs = stale_runs(base, args.days)
        size = sum(item[2] for item in runs)
        print(f'{relative}: {len(runs)} stale run folder(s), {size / 1e6:.1f} MB')
        for path, age, run_size in runs:
            resolved = path.resolve()
            if resolved.parent != base:
                print(f'  skipped (outside root): {path}')
                continue
            print(f'  {"deleting" if args.apply else "would delete"} {path.name} · {age:.0f} days · {run_size / 1e6:.2f} MB')
            if args.apply:
                shutil.rmtree(resolved)
            total_count += 1
            total_bytes += run_size
    verb = 'deleted' if args.apply else 'would delete'
    print(f'Total: {verb} {total_count} folder(s), {total_bytes / 1e6:.1f} MB.')
    if not args.apply and total_count:
        print('Dry run only. Re-run with --apply to delete.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
