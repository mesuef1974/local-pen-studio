import base64,io,unittest
import numpy as np
from PIL import Image
from editor_ops import operate
from lineart_processing import encode,decode
from pen_paths import extract_paths

class EditorTests(unittest.TestCase):
    def setUp(self):
        self.image=np.full((60,80,3),210,np.uint8);self.image[:30,:40]=[180,40,20];self.url=encode(self.image)
    def apply(self,op,settings=None,selection=None):
        body={'image':self.url,'operation':op,'settings':settings or {}}
        if selection is not None:body['selection']=encode(selection)
        return operate(body)
    def test_crop_exact_pixels_and_dimensions(self):
        r=self.apply('crop',{'x':3,'y':4,'width':30,'height':20})
        np.testing.assert_array_equal(decode(r['image']),self.image[4:24,3:33]);self.assertTrue(r['geometry'])
    def test_transparency_survives_filters_export_and_geometry(self):
        rgba=np.dstack((self.image,np.tile(np.arange(80,dtype=np.uint8)*3,(60,1))))
        self.url=encode(rgba)
        for op in ['gray','invert','autocontrast','blur','median','sharpen','threshold','export']:
            actual=decode(self.apply(op)['image'],preserve_alpha=True)
            np.testing.assert_array_equal(actual[:,:,3],rgba[:,:,3],err_msg=op)
        np.testing.assert_array_equal(decode(self.apply('export')['image'],preserve_alpha=True),rgba)
        np.testing.assert_array_equal(decode(self.apply('crop',{'x':3,'y':4,'width':30,'height':20})['image'],preserve_alpha=True),rgba[4:24,3:33])
        np.testing.assert_array_equal(decode(self.apply('flipX')['image'],preserve_alpha=True),rgba[:,::-1])
        np.testing.assert_array_equal(decode(self.apply('rotate',{'angle':90})['image'],preserve_alpha=True),np.rot90(rgba,-1))
        resized=decode(self.apply('resize',{'width':40,'height':30})['image'],preserve_alpha=True)
        np.testing.assert_array_equal(resized,np.asarray(Image.fromarray(rgba).resize((40,30),Image.Resampling.LANCZOS)))
    def test_transparent_selection_does_not_select_hidden_white_pixels(self):
        mask=np.full((60,80,4),255,np.uint8);mask[:,:,3]=0;mask[10:20,10:20,3]=255
        result=decode(self.apply('invert',selection=mask)['image'])
        np.testing.assert_array_equal(result[10:20,10:20],255-self.image[10:20,10:20])
        np.testing.assert_array_equal(result[0],self.image[0])
    def test_pen_modes_ignore_rgb_hidden_under_removed_background(self):
        rgba=np.zeros((60,80,4),np.uint8);rgba[10:50,35:38]=[0,0,0,255]
        white=np.full((60,80,3),255,np.uint8);white[10:50,35:38]=0
        for mode in ['centerline','ink']:
            settings={'lineMode':mode,'lineDenoise':0,'minLength':2,'tolerance':0}
            actual=extract_paths(settings|{'image':encode(rgba)})
            expected=extract_paths(settings|{'image':encode(white)})
            self.assertEqual(actual['paths'],expected['paths'],mode)
    def test_resize_and_rotate(self):
        self.assertEqual(decode(self.apply('resize',{'width':40,'height':30})['image']).shape,(30,40,3))
        r=decode(self.apply('rotate',{'angle':90})['image']);np.testing.assert_array_equal(r,np.rot90(self.image,-1))
    def test_flips_are_geometric(self):
        np.testing.assert_array_equal(decode(self.apply('flipX')['image']),self.image[:,::-1])
        np.testing.assert_array_equal(decode(self.apply('flipY')['image']),self.image[::-1])
    def test_filter_only_changes_selection(self):
        mask=np.zeros_like(self.image);mask[10:20,10:20]=255
        result=decode(self.apply('invert',selection=mask)['image'])
        np.testing.assert_array_equal(result[10:20,10:20],255-self.image[10:20,10:20])
        outside=np.ones((60,80),bool);outside[10:20,10:20]=False
        np.testing.assert_array_equal(result[outside],self.image[outside])
    def test_wand_respects_color_boundary(self):
        r=self.apply('wand',{'x':10,'y':10,'tolerance':10});mask=decode(r['mask'])[:,:,0]
        self.assertEqual(int(np.count_nonzero(mask)),1200);self.assertEqual(int(mask[40,40]),0)
    def test_grayscale_and_threshold(self):
        gray=decode(self.apply('gray')['image']);np.testing.assert_array_equal(gray[:,:,0],gray[:,:,1])
        self.assertEqual(set(np.unique(decode(self.apply('threshold')['image']))),{0,255})
    def test_inpaint_removes_selected_spot(self):
        image=np.full((60,80,3),180,np.uint8);image[28:33,38:43]=0;self.url=encode(image)
        mask=np.zeros_like(image);mask[27:34,37:44]=255
        result=decode(self.apply('inpaint',selection=mask)['image']);self.assertGreater(int(result[30,40,0]),150)
        np.testing.assert_array_equal(result[0],image[0])
    def test_png_records_dpi(self):
        result=self.apply('export',{'dpi':300});im=Image.open(io.BytesIO(base64.b64decode(result['image'].split(',')[1])))
        self.assertAlmostEqual(im.info['dpi'][0],300,places=1)
    def test_limits_and_wrong_selection(self):
        for op,settings in [('resize',{'width':2001}),('crop',{'x':70,'width':30}),('resize',{'width':True}),('resize',{'width':40.5}),('export',{'dpi':72.5}),('export',{'dpi':0})]:
            with self.subTest(op=op,settings=settings),self.assertRaises(ValueError):self.apply(op,settings)
        with self.assertRaises(ValueError):self.apply('invert',selection=np.zeros((5,5,3),np.uint8))
    def test_blur_median_and_sharpen_change_detail(self):
        image=np.random.default_rng(8).integers(30,220,(60,80,3),dtype=np.uint8);self.url=encode(image)
        for op in ['blur','median','sharpen']:
            with self.subTest(op=op):self.assertFalse(np.array_equal(decode(self.apply(op)['image']),image))

    def test_editor_maximum_dimensions_can_reach_pen_extraction(self):
        image=np.full((2000,2000,3),255,np.uint8);image[1000,100:1900]=0
        result=extract_paths({'image':encode(image),'lineMode':'ink','lineDenoise':0,'minLength':2,'tolerance':0})
        self.assertEqual((result['width'],result['height']),(2000,2000))
        self.assertTrue(result['paths'])
    def test_decode_rejects_large_dimensions_before_full_decode_and_foreign_formats(self):
        from unittest.mock import patch
        stream=io.BytesIO();Image.new('1',(5000,5000),1).save(stream,format='PNG',optimize=True)
        self.assertLess(len(stream.getvalue()),6_000_000)
        big='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()
        with patch('lineart_processing.ImageOps.exif_transpose',side_effect=AssertionError('decoded before size check')):
            with self.assertRaisesRegex(ValueError,'أربعة ملايين'):decode(big)
        stream=io.BytesIO();Image.new('RGB',(8,8),'white').save(stream,format='BMP')
        with self.assertRaisesRegex(ValueError,'تعذر قراءة'):decode('data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())
        self.assertEqual(decode(self.url).shape,(60,80,3))

if __name__=='__main__':unittest.main()
