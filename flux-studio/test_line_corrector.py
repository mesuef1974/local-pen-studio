import unittest
import cv2
import numpy as np
from conservative_line_corrector import correct


class LineCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.base = np.zeros((64,64), bool)
        self.base[32,10:51] = True
        self.roi = np.ones((64,64), np.uint8)

    def test_correct_line_unchanged(self):
        result, report = correct(self.base, self.base, self.roi)
        self.assertTrue(np.array_equal(result,self.base))
        self.assertFalse(report['operations'])

    def test_known_short_gap_restored(self):
        broken = self.base.copy(); broken[32,30:32] = False
        result, report = correct(broken,self.base,self.roi)
        self.assertTrue(np.array_equal(result,self.base))
        self.assertEqual(report['operations'][0]['kind'],'bridge_gap')

    def test_isolated_speck_removed(self):
        noisy = self.base.copy(); noisy[10,20] = True
        result, _ = correct(noisy,self.base,self.roi)
        self.assertTrue(np.array_equal(result,self.base))

    def test_protected_dot_preserved(self):
        noisy = self.base.copy(); noisy[10,20] = True
        protection = np.zeros_like(noisy); protection[10,20] = True
        result, _ = correct(noisy,self.base,self.roi,protection)
        self.assertTrue(result[10,20])

    def test_gap_without_support_not_added(self):
        broken = self.base.copy(); broken[32,30:32] = False
        result, _ = correct(broken,broken,self.roi)
        self.assertTrue(np.array_equal(result,broken))

    def test_outside_roi_unchanged(self):
        noisy = self.base.copy(); noisy[10,20] = True
        roi = self.roi.copy(); roi[:20] = 0
        result, _ = correct(noisy,self.base,roi)
        self.assertTrue(np.array_equal(result,noisy))

    def test_no_evidence_abstains(self):
        result, report = correct(self.base,np.zeros_like(self.base),self.roi)
        self.assertEqual(report['state'],'abstained')
        self.assertTrue(np.array_equal(result,self.base))

    def test_large_gap_not_completed(self):
        broken=self.base.copy();broken[32,25:36]=False
        result,_=correct(broken,self.base,self.roi)
        self.assertTrue(np.array_equal(result,broken))

    def test_closed_shape_not_joined_across_itself(self):
        shape=np.zeros((64,64),np.uint8)
        cv2.rectangle(shape,(20,20),(40,40),1,1)
        broken=shape.astype(bool);broken[20,29:31]=False
        result,_=correct(broken,shape>0,self.roi)
        self.assertTrue(np.array_equal(result,broken))

    def test_invalid_shapes_rejected(self):
        with self.assertRaises(ValueError):
            correct(self.base,self.base[:32],self.roi)

    def test_known_small_translation_recovered(self):
        reference = np.zeros((256,256),np.uint8)
        reference[100:200,100:200] = 1
        cv2.rectangle(reference,(20,20),(24,24),1,1)
        shifted = reference.copy()
        shifted[20:25,20:25] = 0
        cv2.rectangle(shifted,(20,22),(24,26),1,1)
        roi = np.zeros_like(reference);roi[10:40,10:40] = 1
        result, report = correct(shifted>0,reference>0,roi)
        self.assertTrue(np.array_equal(result,reference>0))
        self.assertIn('translate_component',[op['kind'] for op in report['operations']])

    def test_transparent_export_preserves_coloured_antialiasing(self):
        from PIL import Image
        from build_line_correction_experiment import transparent
        rgb = np.array([[[255,255,255],[0,0,0],[90,110,100],[248,251,250]]],dtype=np.uint8)
        layer = Image.fromarray(transparent(rgb))
        white = Image.new('RGBA',layer.size,'white')
        white.alpha_composite(layer)
        self.assertLessEqual(int(np.abs(np.asarray(white.convert('RGB')).astype(int)-rgb.astype(int)).max()),1)


if __name__=='__main__':
    unittest.main()
