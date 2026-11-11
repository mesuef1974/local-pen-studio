import io,base64,unittest,json
from types import SimpleNamespace
import tempfile
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
import preparation as p

def data(image,format='PNG'):
    b=io.BytesIO();image.save(b,format=format);return 'data:application/octet-stream;base64,'+base64.b64encode(b.getvalue()).decode()

def source():
    image=Image.new('RGBA',(100,120));draw=ImageDraw.Draw(image);draw.ellipse((15,10,85,110),fill=(180,50,80,255));return image

class PreparationTests(unittest.TestCase):
    @contextmanager
    def background_fixture(self):
        # The worker is mocked; no real runtime or model is needed for unit tests.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'trace-studio'
            root.mkdir()
            python = root.parent / 'drawing-simulator/.venv-background-gpu/Scripts/python.exe'
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(p, 'ROOT', root):
                yield

    def setUp(self):p.CUTOUT_CACHE.clear();p.SUBJECT_CACHE.clear()
    def test_color_background_removal_keeps_source_rgb_and_original_untouched(self):
        image=source().convert('RGB');value=p.encoded(image.convert('RGBA'));cutout=source();pixels=np.asarray(image).copy()
        with patch.object(p,'remove_subject',return_value=p.encoded(cutout)):
            result=p.prepare({'image':value,'settings':{'background':'subject','style':'color','denoise':0,'contrast':100,'brightness':0}},require_transparency=False)
            gray=p.prepare({'image':value,'settings':{'background':'subject','style':'gray','denoise':0}},require_transparency=False)
        actual,_=p.decode(result['image']);mono,_=p.decode(gray['image'])
        self.assertTrue(np.array_equal(np.asarray(actual)[:,:,:3],pixels))
        self.assertTrue(np.array_equal(np.asarray(actual)[:,:,3],np.asarray(cutout)[:,:,3]))
        self.assertTrue(np.array_equal(np.asarray(image),pixels))
        self.assertFalse(np.array_equal(np.asarray(mono)[:,:,:3],pixels))
    def test_direct_background_removal_reuses_identical_image(self):
        value=p.encoded(source());response=SimpleNamespace(returncode=0,stdout=json.dumps({'image':value,'device':'CUDA'}))
        with self.background_fixture(),patch.object(p,'run_bounded',return_value=response) as run:
            self.assertEqual(p.remove_subject(value),value);self.assertEqual(p.remove_subject(value),value)
        self.assertEqual(run.call_count,1)
    def test_unanswering_card_is_queried_and_retried_once(self):
        value=p.encoded(source());asleep=SimpleNamespace(returncode=3,stdout=json.dumps({'error':'كرت NVIDIA غير متاح','retry':'cuda'}))
        awake=SimpleNamespace(returncode=0,stdout=json.dumps({'image':value,'device':'CUDA'}))
        with self.background_fixture(),patch.object(p,'run_bounded',side_effect=[asleep,SimpleNamespace(returncode=0,stdout=''),awake]) as run:
            self.assertEqual(p.remove_subject(value),value)
        self.assertEqual([call.args[0][0] for call in run.call_args_list][1],'nvidia-smi');self.assertEqual(run.call_count,3)
        p.SUBJECT_CACHE.clear()
        with self.background_fixture(),patch.object(p,'run_bounded',side_effect=[asleep,OSError(),asleep,awake]) as run,self.assertRaisesRegex(ValueError,'NVIDIA'):p.remove_subject(value)
        self.assertEqual(run.call_count,3);self.assertEqual(len(p.SUBJECT_CACHE),0)
    def test_empty_model_output_is_not_cached_or_accepted(self):
        value=p.encoded(source());empty=p.encoded(Image.new('RGBA',(100,120)))
        response=SimpleNamespace(returncode=0,stdout=json.dumps({'image':empty,'device':'CUDA'}))
        with self.background_fixture(),patch.object(p,'run_bounded',return_value=response),self.assertRaises(ValueError):p.remove_subject(value)
        self.assertEqual(len(p.SUBJECT_CACHE),0)
    def test_cpu_worker_result_is_rejected_instead_of_silent_fallback(self):
        value=p.encoded(source());response=SimpleNamespace(returncode=0,stdout=json.dumps({'image':value,'device':'CPU'}))
        with self.background_fixture(),patch.object(p,'run_bounded',return_value=response),self.assertRaisesRegex(ValueError,'CUDA'):p.remove_subject(value)
        self.assertEqual(len(p.SUBJECT_CACHE),0)
    def test_import_common_formats_normalizes_without_color_loss(self):
        image=Image.new('RGB',(80,100),(180,50,80))
        for format in ['PNG','JPEG','WEBP','BMP','TIFF','GIF']:
            with self.subTest(format=format):
                result=p.import_image({'image':data(image,format)})
                self.assertTrue(result['image'].startswith('data:image/png;base64,'));self.assertTrue(result['meta']['colored']);self.assertFalse(result['meta']['transparent'])
    def test_existing_alpha_preserved_and_output_gray(self):
        image=source();imported=p.import_image({'image':data(image)})
        with patch.object(p,'remove_subject') as model:
            result=p.prepare({'image':imported['image'],'settings':{}})
        model.assert_not_called();prepared,_=p.decode(result['image']);a=np.asarray(prepared)
        self.assertTrue(np.array_equal(a[:,:,3],np.asarray(image)[:,:,3]));self.assertTrue(np.array_equal(a[:,:,0],a[:,:,1]));self.assertTrue(result['meta']['ready'])
    def test_opaque_keep_does_not_fake_transparency(self):
        imported=p.import_image({'image':data(Image.new('RGB',(80,100),'gray'))})
        with self.assertRaises(ValueError):p.prepare({'image':imported['image'],'settings':{'background':'keep'}})
    def test_model_called_once_for_tonal_changes(self):
        imported=p.import_image({'image':data(source().convert('RGB'))})
        with patch.object(p,'remove_subject',return_value=p.encoded(source())) as model:
            first=p.prepare({'image':imported['image'],'settings':{}})
            second=p.prepare({'image':imported['image'],'settings':{'brightness':20}})
        self.assertEqual(model.call_count,1);self.assertFalse(first['backgroundCached']);self.assertTrue(second['backgroundCached']);self.assertNotEqual(first['image'],second['image'])
    def test_simple_border_removal_is_connected_exterior(self):
        image=Image.new('RGB',(100,120),'white');ImageDraw.Draw(image).rectangle((25,20,75,100),fill='black')
        imported=p.import_image({'image':data(image)})
        result=p.prepare({'image':imported['image'],'settings':{'background':'border','tolerance':5}})
        prepared,_=p.decode(result['image']);self.assertEqual(prepared.getpixel((0,0))[3],0);self.assertEqual(prepared.getpixel((50,50))[3],255)
    def test_tonal_steps_and_ink_are_real(self):
        image=source();a=np.asarray(image).copy();a[:,:,:3]=np.arange(100,dtype=np.uint8)[None,:,None]*2
        imported=p.import_image({'image':data(Image.fromarray(a))})
        for style,limit in [('tones',8),('ink',2)]:
            result=p.prepare({'image':imported['image'],'settings':{'style':style,'levels':8,'denoise':0}})
            prepared,_=p.decode(result['image']);out=np.asarray(prepared);self.assertLessEqual(len(np.unique(out[:,:,0][out[:,:,3]>127])),limit)
    def test_invalid_settings(self):
        for value in [{'levels':1},{'denoise':True},{'brightness':float('nan')},{'style':'unknown'},{'background':'unknown'},{'levels':4.5}]:
            with self.assertRaises(ValueError):p.validate(value)
    def test_cache_is_bounded(self):
        for value in range(4):
            image=source();ImageDraw.Draw(image).point((50,50),fill=(value,0,0,255))
            imported=p.import_image({'image':data(image)});p.prepare({'image':imported['image'],'settings':{}})
        self.assertEqual(len(p.CUTOUT_CACHE),2)
    def test_large_import_is_bounded_and_original_is_untouched(self):
        image=Image.new('RGB',(3000,1000),'red');raw=data(image)
        result=p.import_image({'image':raw});self.assertTrue(result['resized']);self.assertEqual(result['originalWidth'],3000)
        self.assertEqual(result['meta']['width'],2000);self.assertLessEqual(result['meta']['width']*result['meta']['height'],4_000_000)
        self.assertEqual(image.size,(3000,1000));self.assertEqual(raw,data(image))
    def test_animated_import_uses_first_frame_explicitly(self):
        b=io.BytesIO();Image.new('RGB',(40,40),'red').save(b,format='GIF',save_all=True,append_images=[Image.new('RGB',(40,40),'blue')],duration=100,loop=0)
        result=p.import_image({'image':'data:image/gif;base64,'+base64.b64encode(b.getvalue()).decode()})
        self.assertTrue(result['firstFrame']);image,_=p.decode(result['image']);self.assertGreater(image.getpixel((10,10))[0],image.getpixel((10,10))[2])

if __name__=='__main__':unittest.main()
