import unittest
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from centerline_routing import route_junctions
from pen_paths import extract_paths
from lineart_processing import encode

def raster(paths,shape):
    output=np.zeros(shape,np.uint8)
    for path in paths:cv2.polylines(output,[np.asarray(path,np.int32)],False,255,1)
    return output

class RoutingTests(unittest.TestCase):
    def test_t_junction_keeps_branch_and_pairs_straight_line(self):
        paths=[[[5,0],[5,5]],[[5,5],[5,10]],[[5,5],[9,5]]]
        output,stats=route_junctions(paths)
        self.assertEqual(len(output),2);self.assertEqual(stats['junctionPairs'],1)
        np.testing.assert_array_equal(raster(paths,(12,12)),raster(output,(12,12)))
    def test_nearby_unconnected_lines_never_join(self):
        output,stats=route_junctions([[[0,0],[4,0]],[[5,0],[9,0]]])
        self.assertEqual(len(output),2);self.assertEqual(stats['junctionPairs'],0)
    def test_ambiguous_junction_is_not_arbitrarily_paired(self):
        output,stats=route_junctions([[[5,5],[5,0]],[[5,5],[4,10]],[[5,5],[6,10]]])
        self.assertEqual(len(output),3);self.assertEqual(stats['junctionPairs'],0)
    def test_crossing_routes_without_duplicating_edges(self):
        paths=[[[5,5],[0,5]],[[5,5],[10,5]],[[5,5],[5,0]],[[5,5],[5,10]]]
        output,stats=route_junctions(paths)
        self.assertEqual(len(output),2)
        np.testing.assert_array_equal(raster(paths,(12,12)),raster(output,(12,12)))
    def test_reference_lineart_preserves_every_traced_pixel(self):
        image=np.array(Image.open(Path(__file__).parent/'reference-benchmark/reference.png').convert('RGB'))
        args={'image':encode(image),'lineMode':'centerline','minLength':2,'lineDenoise':0,'tolerance':0}
        old=extract_paths({**args,'junctionRouting':False});new=extract_paths(args)
        self.assertLessEqual(len(new['paths']),len(old['paths']))
        np.testing.assert_array_equal(raster(old['paths'],image.shape[:2]),raster(new['paths'],image.shape[:2]))

if __name__=='__main__':unittest.main()
