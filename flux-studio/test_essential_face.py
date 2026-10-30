import unittest
import numpy as np
from essential_face import INDICES, GROUPS, compare


class EssentialFaceTests(unittest.TestCase):
    def setUp(self):
        self.points = np.random.default_rng(42).random((478, 2))

    def test_unique_profile(self):
        self.assertEqual(len(INDICES), 34)
        self.assertEqual(sum(map(len, GROUPS.values())), 34)
        self.assertTrue(all(0 <= i < 478 for i in INDICES))

    def test_translation_uniform_scale(self):
        result = compare(self.points, self.points*3+12)
        self.assertLess(result['rms'], 1e-12)
        self.assertIsNone(result['score'])
        self.assertFalse(result['automaticApproval'])

    def test_unselected_points_do_not_affect_score(self):
        changed = self.points.copy()
        changed[[i for i in range(478) if i not in INDICES]] += 100
        self.assertEqual(compare(self.points, changed)['rms'], 0)

    def test_selected_change_is_measured(self):
        changed = self.points.copy()
        changed[1] += .1
        self.assertGreater(compare(self.points, changed)['groupRMS']['nose'], 0)

    def test_invalid_points(self):
        with self.assertRaises(ValueError):
            compare(np.zeros((478,2)), np.zeros((478,2)))


if __name__ == '__main__':
    unittest.main()
