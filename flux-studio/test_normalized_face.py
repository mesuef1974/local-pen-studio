import unittest
from PIL import Image
from build_normalized_face_preview import fit_square


class NormalizedFaceTests(unittest.TestCase):
    def test_preserves_aspect_and_pads(self):
        result, meta = fit_square(Image.new('RGB',(200,100),'black'), 512)
        self.assertEqual(result.size, (512,512))
        self.assertEqual(meta['resizedSize'], [512,256])
        self.assertEqual(meta['offset'], [0,128])
        self.assertEqual(result.getpixel((256,0)), (255,255,255))
        self.assertEqual(result.getpixel((256,256)), (0,0,0))
        self.assertTrue(meta['upscaled'])

    def test_downscale_metadata(self):
        _, meta = fit_square(Image.new('RGB',(1000,500),'white'), 384)
        self.assertFalse(meta['upscaled'])
        self.assertEqual(meta['nativeCropSize'], [1000,500])
        self.assertEqual(meta['resizedSize'], [384,192])

    def test_target_sizes(self):
        for size in (384,512,768):
            image, _ = fit_square(Image.new('RGB',(80,160)), size)
            self.assertEqual(image.size, (size,size))


if __name__ == '__main__':
    unittest.main()
