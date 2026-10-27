import base64
import io
import sys
import unittest
import tempfile
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import background_service as service


def encode(image):
    output = io.BytesIO(); image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


def decode(value):
    return Image.open(io.BytesIO(base64.b64decode(value.split(',', 1)[1])))


class BackgroundTests(unittest.TestCase):
    @contextmanager
    def model_fixture(self):
        # Only satisfy the file precondition; inference remains mocked below.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'models/background/models/birefnet-general/birefnet-general.onnx'
            model.parent.mkdir(parents=True)
            model.touch()
            with patch.object(service, 'ROOT', root):
                yield

    def test_nonfinite_or_constant_cuda_mask_cannot_be_published(self):
        for value in [float('nan'),0.0]:
            inner=SimpleNamespace(get_inputs=lambda:[SimpleNamespace(name='input')],run=lambda *args: [np.full((1,1,8,8),value,dtype=np.float32)])
            with self.assertRaisesRegex(ValueError,'قناع'):service.cuda_mask(Image.new('RGB',(40,40),'black'),SimpleNamespace(inner_session=inner))

    def test_cuda_is_required_and_runtime_fallback_is_disabled(self):
        inner=SimpleNamespace(get_providers=lambda:['CUDAExecutionProvider','CPUExecutionProvider'],disable_fallback=lambda:None)
        calls=[]
        def create(*args,**kwargs):calls.append(kwargs['providers']);return inner
        ort=SimpleNamespace(get_available_providers=lambda:['CUDAExecutionProvider'],SessionOptions=lambda:SimpleNamespace(),InferenceSession=create)
        torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True))
        with patch.dict(sys.modules,{'torch':torch,'onnxruntime':ort}):
            self.assertIs(service.local_session(service.ROOT/'background_service.py',device='cuda').inner_session,inner)
        self.assertEqual(calls[0][0][0],'CUDAExecutionProvider')

    def test_cuda_missing_provider_or_failed_activation_is_not_cpu_success(self):
        torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True))
        ort=SimpleNamespace(get_available_providers=lambda:['CPUExecutionProvider'],SessionOptions=lambda:SimpleNamespace())
        ort.InferenceSession=lambda *args,**kwargs:SimpleNamespace(get_providers=lambda:['CPUExecutionProvider'])
        with patch.dict(sys.modules,{'torch':torch,'onnxruntime':ort}):
            with self.assertRaisesRegex(ValueError,'CUDA'):service.local_session(service.ROOT/'background_service.py',device='cuda')
            ort.get_available_providers=lambda:['CUDAExecutionProvider']
            with self.assertRaisesRegex(ValueError,'CUDA'):service.local_session(service.ROOT/'background_service.py',device='cuda')

    def test_existing_transparency_never_resurrects_hidden_pixels(self):
        source = Image.new('RGBA', (40, 40), (20, 100, 220, 255))
        source.putpixel((0, 0), (255, 0, 0, 0))
        model = SimpleNamespace(new_session=lambda *a, **kw: None,
                                remove=lambda image, **kw: image.convert('RGBA'))
        with self.model_fixture(),patch.dict(sys.modules, {'rembg': model}),patch.object(service,'local_session',return_value=None):
            result = decode(service.run({'image': encode(source)})['image'])
        self.assertEqual(result.convert('RGB').getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(source.getpixel((0, 0)), (255, 0, 0, 0))

    def test_transparent_output_preserves_rgb_and_multiplies_both_masks(self):
        source=Image.new('RGBA',(40,40),(10,90,180,128));source.putpixel((0,0),(255,0,0,0))
        seen=[]
        def remove(image,**kwargs):
            seen.append(image.copy())
            return Image.new('RGBA',image.size,(255,255,255,128))
        with self.model_fixture(),patch.dict(sys.modules,{'rembg':SimpleNamespace(remove=remove)}),patch.object(service,'local_session',return_value=None):
            result=decode(service.run({'image':encode(source)},transparent=True)['image'])
        self.assertEqual(result.mode,'RGBA');self.assertEqual(result.getpixel((1,1)),(10,90,180,64))
        self.assertEqual(result.getpixel((0,0))[3],0);self.assertEqual(seen[0].getpixel((0,0)),(255,255,255))

    def test_invalid_input_is_rejected_before_loading_model(self):
        for image in ['http://example.com/photo.png','data:image/png;base64,AAAA']:
            with self.model_fixture(),patch.object(service,'local_session') as session,self.assertRaises((ValueError,OSError)):
                service.run({'image':image})
            session.assert_not_called()


if __name__ == '__main__': unittest.main()
