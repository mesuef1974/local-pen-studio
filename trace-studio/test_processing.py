import base64,io,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import processing as p


def url(image):
    b=io.BytesIO();image.save(b,format='PNG');return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()


class ValidationTests(unittest.TestCase):
    def source(self,color=(60,60,60,255)):
        image=Image.new('RGBA',(80,100),(0,0,0,0));image.paste(color,(10,10,70,90));return image
    def test_ready_monochrome(self):self.assertTrue(p.inspect({'image':url(self.source())})['ready'])
    def test_opaque_rejected_before_skill(self):
        with patch.object(p,'invoke') as call,self.assertRaises(ValueError):p.run_trace({'image':url(Image.new('RGB',(80,100),'gray'))})
        call.assert_not_called()
    def test_color_never_silently_desaturated(self):
        source=url(self.source((200,20,30,255)));self.assertTrue(p.inspect({'image':source})['colored'])
        with patch.object(p,'invoke') as call,self.assertRaises(ValueError):p.run_trace({'image':source})
        call.assert_not_called()
    def test_empty_alpha_not_ready(self):self.assertFalse(p.inspect({'image':url(Image.new('RGBA',(30,30)))})['ready'])
    def test_bad_png(self):
        for value in ['',None,'data:image/png;base64,bad!','data:image/jpeg;base64,abc']:
            with self.assertRaises(ValueError):p.decode(value)
    def test_bounds(self):
        for values in [dict(median=2),dict(alphaSigma=-1),dict(tolerance=float('nan')),dict(turdsize=True),dict(component=301),dict(alphamax=2),dict(resolution=20),dict(component=1.2),dict(other=1)]:
            with self.subTest(values=values),self.assertRaises(ValueError):p.validated(values)
    def test_opaque_grayscale_does_not_remove_background(self):
        with patch.object(p,'invoke') as call,self.assertRaises(ValueError):p.grayscale({'image':url(Image.new('RGB',(80,100),'red'))})
        call.assert_not_called()
    def test_download_route_only_allows_known_files_and_job_ids(self):
        from server import Handler
        handler=object.__new__(Handler)
        for filename in p.OUTPUT_FILES.values():
            handler.path='/output/'+'a'*32+'/'+filename
            self.assertEqual(handler.route(),'output/'+'a'*32+'/'+filename)
        for path in ['/output/../../processing.py','/output/'+'a'*32+'/approved-input.png','/output/not-a-job/trace-vector.svg','/processing.py']:
            handler.path=path;self.assertIsNone(handler.route())


@unittest.skipUnless(shutil.which('wsl.exe') and shutil.which('node'),'Requires installed local WSL skill runtime and Node')
class SkillIntegrationTests(unittest.TestCase):
    def test_all_nine_preferences_real_skill_and_renderer(self):
        root=Path(__file__).parent
        code="const fs=require('fs'),vm=require('vm');const s=fs.readFileSync('app.js','utf8');console.log(JSON.stringify(vm.runInNewContext(s.slice(s.indexOf('const recipes=['),s.indexOf('const fields=['))+';recipes')));"
        recipes=json.loads(subprocess.check_output(['node','-e',code],cwd=root,text=True,encoding='utf-8'))
        image=Image.open(root/'sample.png').convert('RGBA');image.thumbnail((160,200));source=url(image)
        with tempfile.TemporaryDirectory() as folder,patch.object(p,'ROOT',Path(folder)):
            jobs=set()
            for name,_,_,options in recipes:
                with self.subTest(preset=name):
                    result=p.run_trace({'image':source,'settings':options});self.assertGreater(result['segments'],0);self.assertEqual(result['rasters'],0)
                    self.assertNotIn(result['job'],jobs);jobs.add(result['job'])
                    output=Path(folder)/'output'/result['job']
                    self.assertTrue(all((output/file).is_file() for file in p.OUTPUT_FILES.values()))
                    report=json.loads((output/'trace-validation.json').read_text())
                    self.assertTrue(report['master_reference_locked']);self.assertEqual(report['embedded_rasters_final'],0)
                    preview=Image.open(output/'trace-preview.png').convert('RGBA')
                    self.assertEqual(preview.getpixel((0,0))[3],0)
                    self.assertEqual(preview.getpixel((round(preview.width/2),round(preview.height*375/760)))[3],0,'negative-space eye must remain transparent')
            self.assertEqual(len(jobs),9)
    def test_explicit_grayscale_uses_skill_preserves_alpha(self):
        image=Image.new('RGBA',(30,40));image.paste((200,20,30,180),(5,5,25,35))
        result=p.grayscale({'image':url(image)})
        a=np.asarray(Image.open(io.BytesIO(base64.b64decode(result['image'].split(',')[1]))).convert('RGBA'))
        self.assertTrue(np.array_equal(a[:,:,3],np.asarray(image)[:,:,3]));self.assertTrue(np.array_equal(a[:,:,0],a[:,:,1]));self.assertTrue(np.array_equal(a[:,:,1],a[:,:,2]))


if __name__=='__main__':unittest.main()
