"""Behavior checks for the actual image sent to the line-art model."""
import unittest
import numpy as np
from lineart_processing import process, encode, decode


class InputAdjustmentsTests(unittest.TestCase):
    def apply(self, image, **settings):
        return decode(process({'action': 'pre', 'image': encode(image), 'settings': settings})['image'])

    def test_neutral_preserves_original_exactly(self):
        image=np.random.default_rng(7).integers(0,256,(40,50,3),dtype=np.uint8)
        np.testing.assert_array_equal(self.apply(image),image)

    def test_exposure_and_midtone_controls_brighten_and_darken(self):
        image=np.full((20,20,3),100,np.uint8)
        for name,positive,negative in [('exposure',1,-1),('brightness',30,-30),('gamma',150,70)]:
            with self.subTest(control=name):
                self.assertGreater(self.apply(image,**{name:positive}).mean(),100)
                self.assertLess(self.apply(image,**{name:negative}).mean(),100)

    def test_shadow_and_highlight_masks_target_different_tones(self):
        image=np.full((20,40,3),200,np.uint8);image[:,:20]=50
        for control,region in [('shadows',0),('blacks',0),('highlights',1),('whites',1)]:
            with self.subTest(control=control):
                delta=self.apply(image,**{control:40}).astype(float)-image
                dark=delta[:,:20].mean();light=delta[:,20:].mean()
                self.assertGreater(dark if region==0 else light,light if region==0 else dark)
                self.assertTrue((self.apply(image,**{control:-40})<=image).all())

    def test_color_and_detail_controls_change_real_pixels(self):
        image=np.random.default_rng(42).integers(40,210,(40,50,3),dtype=np.uint8)
        for control,value in [('saturation',0),('warmth',70),('sharpness',60),('tonalContrast',140)]:
            with self.subTest(control=control):
                self.assertFalse(np.array_equal(self.apply(image,**{control:value}),image))
        gray=self.apply(image,saturation=0)
        np.testing.assert_array_equal(gray[:,:,0],gray[:,:,1])
        np.testing.assert_array_equal(gray[:,:,1],gray[:,:,2])

    def test_temperature_moves_red_and_blue_oppositely(self):
        image=np.full((20,20,3),128,np.uint8)
        warm=self.apply(image,warmth=100)
        self.assertGreater(int(warm[0,0,0]),128)
        self.assertLess(int(warm[0,0,2]),128)

    def test_extreme_adjustments_clip_without_wrapping(self):
        image=np.full((20,20,3),230,np.uint8)
        output=self.apply(image,exposure=2,brightness=60,shadows=100,highlights=100)
        self.assertEqual(int(output.min()),255)

    def test_clipping_diagnostic_ignores_existing_white_background(self):
        image=np.full((20,40,3),255,np.uint8);image[:,:20]=180
        neutral=process({'action':'pre','image':encode(image),'settings':{}})
        self.assertEqual(neutral['newlyClippedHighlightsPercent'],0)
        bright=process({'action':'pre','image':encode(image),'settings':{'exposure':2}})
        self.assertEqual(bright['newlyClippedHighlightsPercent'],50)

    def test_bad_values_are_rejected(self):
        image=np.full((20,20,3),100,np.uint8)
        for settings in [{'exposure':3},{'brightness':True},{'gamma':float('nan')},
                         {'shadows':-101},{'highlights':float('inf')},{'saturation':181}]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                self.apply(image,**settings)


if __name__=='__main__':unittest.main()
