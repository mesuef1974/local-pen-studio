import base64
import io
import unittest

import cv2
import numpy as np
from PIL import Image
from processing import process, encode, settings


def pixels(url):
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(url.split(',',1)[1]))))


class EdgePipelineTests(unittest.TestCase):
    def setUp(self):
        self.image=np.full((160,220,3),235,np.uint8)
        cv2.rectangle(self.image,(25,20),(125,135),(20,20,20),3)
        cv2.circle(self.image,(165,75),25,(75,110,140),-1)
        self.encoded=encode(self.image)

    def run_image(self,**s):return process({'image':self.encoded,'settings':s})

    def test_all_six_methods_produce_edges(self):
        for method in ['canny','ed','sobel','scharr','laplacian','morph']:
            with self.subTest(method=method):
                result=self.run_image(method=method)
                self.assertEqual((result['width'],result['height']),(220,160))
                self.assertGreater(result['edgePixels'],0)
                self.assertLess(result['coverage'],50)

    def test_transparent_export_is_real_alpha(self):
        a=pixels(self.run_image(background='transparent',ink='#cc3377')['image'])
        self.assertEqual(a.shape,(160,220,4))
        self.assertTrue(np.any(a[:,:,3]==0));self.assertTrue(np.any(a[:,:,3]==255))
        self.assertTrue(np.all(a[a[:,:,3]>0,:3]==[204,51,119]))

    def test_white_and_black_background(self):
        for background,expected in [('white',255),('black',0)]:
            a=pixels(self.run_image(background=background)['image'])
            self.assertTrue(np.all(a[0,0,:3]==expected));self.assertTrue(np.all(a[:,:,3]==255))

    def test_brightness_and_channel_change_prepared_pixels(self):
        plain=pixels(self.run_image(noise='none')['prepared'])
        bright=pixels(self.run_image(noise='none',brightness=15)['prepared'])
        self.assertGreater(bright.mean(),plain.mean())
        red=pixels(self.run_image(channel='red')['prepared'])
        blue=pixels(self.run_image(channel='blue')['prepared'])
        self.assertFalse(np.array_equal(red,blue))

    def test_every_noise_filter_runs(self):
        for noise in ['none','gaussian','bilateral','median','nlm']:
            self.assertGreater(self.run_image(noise=noise)['edgePixels'],0)

    def test_ed_options_and_pf_mode(self):
        for operator in range(4):self.assertGreater(self.run_image(method='ed',edOperator=operator)['edgePixels'],0)
        self.assertGreater(self.run_image(method='ed',pf=True)['edgePixels'],0)

    def test_direction_changes_gradient(self):
        x=self.run_image(method='sobel',direction='x')['image']
        y=self.run_image(method='sobel',direction='y')['image']
        self.assertNotEqual(x,y)

    def test_threshold_changes_edge_count(self):
        weak=self.run_image(method='sobel',edgeThreshold=5)['edgePixels']
        strong=self.run_image(method='sobel',edgeThreshold=230)['edgePixels']
        self.assertGreater(weak,strong)

    def test_thickness_increases_ink(self):
        self.assertGreater(self.run_image(thickness=3)['edgePixels'],self.run_image(thickness=1)['edgePixels'])

    def test_cleanup_removes_small_components(self):
        clean=self.run_image(component=500)
        self.assertGreater(clean['removedComponents'],0)
        self.assertLess(clean['edgePixels'],self.run_image()['edgePixels'])

    def test_constant_image_no_false_edges(self):
        image=encode(np.full((80,80,3),255,np.uint8))
        for method in ['canny','sobel','scharr','laplacian','morph']:
            self.assertEqual(process({'image':image,'settings':{'method':method,'autoThreshold':True}})['edgePixels'],0)

    def test_image_not_upscaled(self):
        result=self.run_image(resolution=2000)
        self.assertEqual(result['width'],220)

    def test_downsample_preserves_aspect(self):
        self.encoded=encode(np.zeros((300,600,3),np.uint8))
        result=self.run_image(resolution=256)
        self.assertEqual((result['width'],result['height']),(256,128))

    def test_overlay_zero_is_original(self):
        self.assertTrue(np.array_equal(pixels(self.run_image(overlayOpacity=0)['overlay']),self.image))

    def test_neutral_preparation_exact_identity(self):
        a=np.tile(np.arange(256,dtype=np.uint8),(32,1))
        rgb=cv2.cvtColor(a,cv2.COLOR_GRAY2RGB)
        prepared=process({'image':encode(rgb),'settings':{'noise':'none'}})['prepared']
        self.assertTrue(np.array_equal(pixels(prepared),a))

    def test_bad_settings_rejected(self):
        for value in [{'method':'unknown'},{'kernel':4},{'sigma':float('nan')},{'thin':1},{'low':200,'high':100},{'ink':'red'},{'component':501},{'unknown':1},{'scan':1.5}]:
            with self.subTest(value=value),self.assertRaises(ValueError):settings(value)

    def test_invalid_image_rejected(self):
        for value in ['',None,'data:image/png;base64,INVALID!!']:
            with self.assertRaises(ValueError):process({'image':value})


if __name__=='__main__':unittest.main()
