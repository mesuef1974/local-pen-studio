"""Behavior checks for masked cleanup and opt-in skeleton pruning."""
import unittest
import cv2
import numpy as np
from lineart_processing import process, encode, decode
from pen_paths import extract_paths

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.image=np.full((80,80,3),255,np.uint8)
        self.image[15:65,30:33]=90;self.image[10,10]=0
        self.url=encode(self.image)
    def apply(self,settings,mask=None):
        body={'action':'post','image':self.url,'settings':settings}
        if mask is not None:body['mask']=encode(mask)
        return decode(process(body)['image'])
    def test_neutral_preserves_pixels(self):
        self.assertTrue(np.array_equal(self.apply({}),self.image))
    def test_protection_restores_raw_after_cleanup(self):
        mask=np.zeros_like(self.image);mask[15:65,30:33]=[255,0,0]
        cleaned=self.apply({'weak':80,'specks':5},mask)
        self.assertTrue(np.array_equal(cleaned[15:65,30:33],self.image[15:65,30:33]))
        self.assertEqual(int(cleaned[10,10,0]),255)
    def test_erase_and_lighten_are_local(self):
        mask=np.zeros_like(self.image);mask[20:25,30:33]=[0,0,255];mask[30:35,30:33]=[0,255,0]
        result=self.apply({'localReduction':50},mask)
        self.assertEqual(int(result[22,31,0]),255)
        self.assertGreater(int(result[32,31,0]),90)
        self.assertEqual(int(result[40,31,0]),90)
    def test_weight_and_binary_affect_pixels(self):
        thick=self.apply({'weight':1});thin=self.apply({'weight':-1})
        self.assertGreater(int((thick[:,:,0]<200).sum()),int((thin[:,:,0]<200).sum()))
        self.assertEqual(set(np.unique(self.apply({'binary':True}))),{0,255})

    def test_protected_binary_ink_uses_selected_threshold(self):
        self.image[15:65,30:33]=150;self.url=encode(self.image)
        mask=np.zeros_like(self.image);mask[15:65,30:33]=[255,0,0]
        result=self.apply({'binary':True,'threshold':120},mask)
        self.assertEqual(int(result[30,31,0]),255)
    def test_preparation_crop_and_bounds(self):
        data=process({'action':'pre','image':self.url,'settings':{'cropX':25,'cropW':50}})
        self.assertEqual(data['width'],40)
        with self.assertRaises(ValueError):process({'action':'pre','image':self.url,'settings':{'cropX':90,'cropW':100}})
    def test_wrong_mask_size_rejected(self):
        with self.assertRaises(ValueError):self.apply({},np.zeros((10,10,3),np.uint8))
    def test_pre_filters_really_change_pixels(self):
        image=np.random.default_rng(42).integers(40,210,(80,80,3),dtype=np.uint8)
        for settings in ({'denoise':80},{'contrast':60}):
            output=decode(process({'action':'pre','image':encode(image),'settings':settings})['image'])
            self.assertFalse(np.array_equal(image,output))

class SkeletonTests(unittest.TestCase):
    def test_explicit_threshold_controls_faint_ink(self):
        image=np.full((50,50,3),255,np.uint8);image[25,5:45]=150
        body={'image':encode(image),'lineMode':'centerline','lineDenoise':0,'minLength':2,'tolerance':0}
        self.assertEqual(extract_paths({**body,'inkThreshold':120})['paths'],[])
        self.assertEqual(len(extract_paths({**body,'inkThreshold':200})['paths']),1)
    def test_short_junction_spur_removed_but_loop_preserved(self):
        image=np.full((100,100,3),255,np.uint8)
        cv2.line(image,(25,10),(25,80),(0,0,0),1)
        cv2.line(image,(25,40),(29,40),(0,0,0),1)
        cv2.circle(image,(70,50),12,(0,0,0),1)
        body={'image':encode(image),'lineMode':'centerline','lineDenoise':0,'minLength':2,'tolerance':0}
        original=extract_paths(body)['paths'];pruned=extract_paths({**body,'spurLength':6})['paths']
        self.assertTrue(any([29,40] in p for p in original))
        self.assertFalse(any([29,40] in p for p in pruned))
        self.assertTrue(any(p[0]==p[-1] and len(p)>20 for p in pruned))

if __name__=='__main__':unittest.main()
