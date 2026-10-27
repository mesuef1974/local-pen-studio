import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import generation
import server
import setup_generation
import test_server
from test_server import source


class GenerationTests(unittest.TestCase):
    def test_preserving_watercolor_never_loads_diffusion_or_cuda(self):
        import sys,base64
        from generation_service import run
        events=[];image=source()
        with patch.dict(sys.modules,{'torch':None,'diffusers':None}),patch('generation_service.emit',side_effect=events.append):
            run({'image':image,'style':'watercolor','preserveSource':True,'resolution':512,'strength':.48})
        result=events[-1]['result']
        self.assertEqual(result['engine'],'opencv');self.assertEqual(result['device'],'cpu')
        self.assertTrue(result['preserveSource']);self.assertIsNone(result['seed'])
        from PIL import Image
        decoded=Image.open(io.BytesIO(base64.b64decode(result['image'].split(',')[1])))
        self.assertEqual(decoded.size,(512,512))
    def test_source_watercolor_keeps_source_hues_and_dimensions(self):
        import cv2,numpy as np
        from PIL import Image
        from generation_service import source_watercolor
        source_pixels=np.zeros((80,100,3),np.uint8);source_pixels[:]=[205,148,105];source_pixels[:,50:]=[60,140,180]
        image=Image.fromarray(source_pixels);before=image.tobytes();result=source_watercolor(image,.48)
        source_hsv=cv2.cvtColor(source_pixels,cv2.COLOR_RGB2HSV);out=cv2.cvtColor(np.asarray(result),cv2.COLOR_RGB2HSV)
        difference=np.abs(out[:,:,0].astype(int)-source_hsv[:,:,0].astype(int));difference=np.minimum(difference,180-difference)
        self.assertLessEqual(int(difference.max()),2)
        self.assertEqual(result.size,image.size);self.assertEqual(before,image.tobytes())
    def test_preservation_flag_is_explicit_and_not_used_for_other_styles(self):
        for data in [{'style':'watercolor','preserveSource':'true'},{'style':'caricature','preserveSource':True}]:
            with self.assertRaises(ValueError):generation.validate({'image':source()}|data)
        self.assertFalse(generation.validate({'image':source(),'style':'watercolor'})['preserveSource'])
    def test_source_processing_does_not_require_sdxl_weights(self):
        gate=threading.Lock();jobs=generation.Jobs(gate)
        with patch.object(generation,'availability',return_value=(False,'no weights')) as availability,patch.object(generation.threading,'Thread'):
            jobs.start({'image':source(),'style':'watercolor','preserveSource':True})
            availability.assert_not_called()
        self.assertTrue(gate.locked());gate.release()
    def test_pencil_finish_is_graphite_even_when_model_keeps_photo_colors(self):
        from generation_service import finish_style
        from PIL import Image,ImageDraw
        import numpy as np
        image=Image.new('RGB',(160,180),(190,120,70))
        ImageDraw.Draw(image).ellipse((25,20,135,160),fill=(230,170,120),outline=(25,35,45),width=3)
        before=image.tobytes();result=finish_style(image,'pencil');pixels=np.asarray(result)
        self.assertTrue(np.array_equal(pixels[:,:,0],pixels[:,:,1]))
        self.assertTrue(np.array_equal(pixels[:,:,1],pixels[:,:,2]))
        self.assertGreater(int(pixels.max())-int(pixels.min()),100)
        self.assertEqual(result.size,image.size);self.assertEqual(before,image.tobytes())
    def test_ink_finish_is_black_white_and_preserves_other_style_images(self):
        from generation_service import finish_style
        from PIL import Image,ImageDraw
        image=Image.new('RGB',(100,100),(180,130,100));ImageDraw.Draw(image).rectangle((25,25,75,75),outline='black',width=3)
        result=finish_style(image,'ink')
        self.assertEqual(result.size,image.size)
        self.assertEqual(set(result.convert('L').tobytes()),{0,255})
        self.assertIs(finish_style(image,'watercolor'),image)
        self.assertEqual(image.getpixel((0,0)),(180,130,100))
    def test_each_style_builds_distinct_prompts_and_compatible_negatives(self):
        prompts=[]
        for style in generation.STYLES:
            settings=generation.validate({'image':source(),'style':style,'prompt':'same subject'})
            positive,negative=generation.prompts(settings)
            self.assertIn(generation.STYLES[style],positive);self.assertIn('same subject',positive)
            self.assertIn(generation.STYLE_NEGATIVES[style],negative)
            self.assertEqual(settings['strength'],generation.STYLE_DEFAULTS[style]['strength'])
            prompts.append(positive)
        self.assertEqual(len(set(prompts)),5)
        watercolor=generation.prompts(generation.validate({'image':source(),'style':'watercolor'}))[1]
        self.assertNotIn('watercolor',watercolor)
    def test_defaults_and_uploaded_image_are_preserved(self):
        image = source()
        result = generation.validate({'image': image})
        self.assertEqual(result['image'], image)
        self.assertEqual(result['style'], 'caricature')
        self.assertEqual(result['resolution'], 1024)
        self.assertIn('caricature', result['stylePrompt'])

    def test_invalid_controls_and_images_fail_before_gpu(self):
        values = [{'style': []}, {'style': 'unknown'}, {'steps': True}, {'seed': -1},
                  {'steps': 41}, {'strength': float('nan')}, {'resolution': 600},
                  {'guidance': float('inf')}, {'prompt': 'a' * 1201},
                  {'image': 'http://example.com/image.png'}, {'image': 'data:image/png;base64,AAAA'}]
        for valueset in values:
            with self.subTest(valueset=valueset), self.assertRaises(ValueError):
                generation.validate({'image': source()} | valueset)

    def test_download_manifest_requires_complete_expected_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python = root / 'python.exe'; python.touch()
            manifest = {'model': generation.MODEL_ID, 'revision': generation.REVISION,
                        'files': {'weights': {'bytes': 3}}}
            (root / 'weights').write_bytes(b'abc')
            (root / 'verified.json').write_text(json.dumps(manifest))
            with patch.multiple(generation, PYTHON=python, MODEL_DIR=root, FILES=['weights']):
                self.assertTrue(generation.availability()[0])
                (root / 'weights').write_bytes(b'ab')
                self.assertFalse(generation.availability()[0])

    def test_busy_compute_gate_rejects_new_generation(self):
        gate = threading.Lock(); jobs = generation.Jobs(gate)
        gate.acquire()
        with patch.object(generation, 'availability', return_value=(True, '')):
            with self.assertRaises(BlockingIOError): jobs.start({'image': source()})
        self.assertTrue(gate.locked())
        gate.release()

    def test_interrupted_download_journal_is_recovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'weights.partial').write_bytes(b'xxx')
            (root / 'weights.chunks.json').write_text('{interrupted')
            response = SimpleNamespace(status_code=206, headers={'Content-Range': 'bytes 0-2/3'},
                                       content=b'abc', raise_for_status=lambda: None)
            from unittest.mock import MagicMock
            context = MagicMock(); context.__enter__.return_value = response
            with patch.object(setup_generation, 'MODEL_DIR', root), patch('requests.get', return_value=context):
                result = setup_generation.download_large('weights', 3)
            self.assertEqual(result.read_bytes(), b'abc')
            self.assertEqual(json.loads((root / 'weights.chunks.json').read_text()), [0])

    def test_success_progress_and_failure_both_release_gpu_gate(self):
        for code in [0, 1]:
            gate = threading.Lock(); jobs = generation.Jobs(gate)
            events = [{'state': 'running', 'step': 1, 'total': 12},
                      {'result': {'image': source(), 'width': 100, 'height': 120}}]
            fake = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO('\n'.join(map(json.dumps, events))),
                                   wait=lambda: code, poll=lambda: code, kill=lambda: None)
            with patch.object(generation, 'availability', return_value=(True, '')), \
                 patch.object(generation.threading, 'Thread'):
                first = jobs.start({'image': source()})
            self.assertTrue(gate.locked()); self.assertEqual(jobs.status()['job']['id'], first['job'])
            with tempfile.TemporaryDirectory() as folder, patch.object(generation, 'ROOT', Path(folder)), patch.object(generation.subprocess, 'Popen', return_value=fake):
                jobs._run(generation.validate({'image': source()}))
            self.assertFalse(gate.locked())
            job = jobs.status()['job']
            self.assertEqual(job['state'], 'complete' if code == 0 else 'failed')
            self.assertEqual(job['step'], 1); self.assertEqual(job['total'], 12)

    def test_generation_http_is_async_and_preserves_origin_checks(self):
        handler = test_server.PipelineServerTests.handler(self, '/api/generate')
        responses = []; handler.reply = lambda code, data: responses.append((code, data))
        with patch.object(server.GENERATION, 'start', return_value={'job': 'test'}) as start:
            handler.do_POST(); start.assert_called_once_with({})
        self.assertEqual(responses, [(202, {'job': 'test'})])
        responses.clear(); handler.headers.replace_header('Origin', 'http://outside.test')
        with patch.object(server.GENERATION, 'start') as start:
            handler.do_POST(); start.assert_not_called()
        self.assertEqual(responses[0][0], 403)


if __name__ == '__main__': unittest.main()
