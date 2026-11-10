import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

import prune_old_outputs as prune

OLD = 'a' * 32
NEW = 'b' * 32


class PruneOldOutputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'trace-studio' / 'output'
        self.output.mkdir(parents=True)
        for name in (OLD, NEW, 'keep-me', 'c' * 31):
            folder = self.output / name
            folder.mkdir()
            (folder / 'result.svg').write_text('x', encoding='utf-8')
        old_time = time.time() - 40 * 86400
        os.utime(self.output / OLD, (old_time, old_time))
        os.utime(self.output / 'keep-me', (old_time, old_time))
        os.utime(self.output / ('c' * 31), (old_time, old_time))

    def run_main(self, *arguments):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = prune.main(['--root', str(self.root), *arguments])
        return code, buffer.getvalue()

    def test_dry_run_deletes_nothing_and_reports(self):
        code, output = self.run_main('--days', '30')
        self.assertEqual(code, 0)
        self.assertIn('would delete', output)
        self.assertTrue((self.output / OLD).exists())

    def test_apply_deletes_only_stale_hex_run_folders(self):
        self.run_main('--days', '30', '--apply')
        self.assertFalse((self.output / OLD).exists())
        self.assertTrue((self.output / NEW).exists())
        self.assertTrue((self.output / 'keep-me').exists())
        self.assertTrue((self.output / ('c' * 31)).exists())

    def test_missing_roots_are_ignored(self):
        empty = Path(self.temp.name) / 'empty'
        empty.mkdir()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(prune.main(['--root', str(empty)]), 0)
        self.assertIn('0 folder', buffer.getvalue())


if __name__ == '__main__':
    unittest.main()
