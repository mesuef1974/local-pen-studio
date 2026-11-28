"""Cut piece: one connected part, real millimetres, and requests refused before any rendering."""
import re
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import cut_design


def word(upright=False):
    """A stand-in for rendered text: a bar with a loose dot and, optionally, a rising stroke."""
    ink = np.zeros((600, 900), np.uint8)
    cv2.rectangle(ink, (0, 360), (899, 460), 255, -1)
    cv2.circle(ink, (650, 560), 36, 255, -1)
    if not upright:
        cv2.line(ink, (200, 400), (450, 40), 255, 60)
    return ink


class ComposeTests(unittest.TestCase):
    def test_one_piece_at_the_requested_size(self):
        piece = cut_design.compose(word(), 150)
        self.assertEqual((piece['pieces'], max(piece['widthMm'], piece['heightMm'])), (1, 150.0))
        self.assertIn(f'width="{piece["widthMm"]:.1f}', piece['svg'])
        self.assertTrue(piece['preview'].startswith('data:image/png;base64,'))
        first = [float(re.search(r'M([\d.]+),', piece[key]).group(1)) for key in ('svg', 'mirroredSvg')]
        self.assertAlmostEqual(sum(first), piece['widthMm'], delta=0.1)

    def test_the_name_alone_reaches_the_ring_on_both_sides(self):
        layer = cut_design.place_name(word())
        ys, xs = np.nonzero(layer > 127)
        away = (np.column_stack([xs, ys]) - cut_design.C) / cut_design.S
        radius = np.hypot(*away.T)
        self.assertGreater(radius.max(), cut_design.IN + 1)
        self.assertLess(radius.max(), cut_design.IN + 4)
        contact = away[radius > cut_design.IN + 1]
        self.assertTrue(contact[:, 0].min() < 0 < contact[:, 0].max())


class RequestTests(unittest.TestCase):
    def test_bad_requests_are_refused_before_rendering(self):
        bad = [{}, {'name': ' '}, {'name': 'a' * 31}, {'name': 'a\x00'}, {'name': 'مسك', 'sizeMm': 20},
               {'name': 'مسك', 'sizeMm': True}, {'name': 'مسك', 'sizeMm': float('nan')}]
        with patch.object(cut_design, 'render_name') as render:
            for data in bad:
                with self.subTest(data=data), self.assertRaises(ValueError):
                    cut_design.design(data)
        render.assert_not_called()

    def test_unknown_font_is_refused(self):
        with self.assertRaises(ValueError):
            cut_design.render_name('مسك', "x'; calc; '")

    @unittest.skipUnless(sys.platform == 'win32', 'name rendering uses Windows GDI+')
    def test_text_is_data_not_script(self):
        # Arial: CI's Windows Server image lacks the Arabic supplemental fonts.
        with patch.object(cut_design, 'FONTS', ('Arial',)):
            ink = cut_design.render_name("a'); throw 1 #", 'Arial')
        self.assertGreater(ink.shape[1], ink.shape[0])


if __name__ == '__main__':
    unittest.main()
