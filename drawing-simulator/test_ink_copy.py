import unittest
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from ink_fill_paths import copy_ink
from test_centerline_routing import raster

class InkCopyTests(unittest.TestCase):
    def test_filled_areas_holes_and_detached_lines_are_copied_exactly(self):
        mask=np.zeros((80,100),np.uint8)
        cv2.rectangle(mask,(5,5),(40,35),255,-1);cv2.circle(mask,(20,20),6,0,-1)
        cv2.line(mask,(50,10),(90,65),255,2);mask[75,1]=255
        paths=copy_ink(mask)
        self.assertEqual(cv2.connectedComponents(raster(paths,mask.shape),8)[0]-1,3)
        np.testing.assert_array_equal(raster(paths,mask.shape),mask)
    def test_nearby_components_do_not_get_white_bridges(self):
        mask=np.zeros((30,30),np.uint8);mask[5:15,5]=255;mask[5:15,7]=255
        paths=copy_ink(mask);self.assertEqual(len(paths),2)
        np.testing.assert_array_equal(raster(paths,mask.shape),mask)
    def test_large_fill_is_bounded(self):
        with self.assertRaises(ValueError):copy_ink(np.full((400,400),255,np.uint8))
    def test_reference_ink_is_copied_without_extra_or_missing_pixels(self):
        image=np.array(Image.open(Path(__file__).parent/'reference-benchmark/reference.png').convert('L'))
        _,mask=cv2.threshold(image,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        np.testing.assert_array_equal(raster(copy_ink(mask),mask.shape),mask)

if __name__=='__main__':unittest.main()
