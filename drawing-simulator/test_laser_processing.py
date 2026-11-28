import base64
import io
import unittest
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

from laser_processing import prepare_laser


def url(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def half(width=400, height=200):
    image = Image.new("L", (width, height), 255)
    ImageDraw.Draw(image).rectangle([0, 0, width // 2 - 1, height], fill=0)
    return image


def request(image, **extra):
    return {"image": url(image), "material": "wood", "operation": "engrave", "widthMm": 50, **extra}


def decoded(result):
    return base64.b64decode(result["file"].split(",", 1)[1])


class LaserProcessingTest(unittest.TestCase):
    def test_engrave_png_has_physical_size(self):
        result = prepare_laser(request(half()))
        png = Image.open(io.BytesIO(decoded(result)))
        self.assertEqual(png.size, (500, 250))
        self.assertAlmostEqual(png.info["dpi"][0], 254, delta=0.1)
        self.assertEqual((result["widthMm"], result["heightMm"]), (50, 25))
        self.assertEqual(result["name"], "masar-wood-engrave-50x25mm.png")

    def test_mirror_and_invert(self):
        def corners(**options):
            png = Image.open(io.BytesIO(decoded(prepare_laser(request(half(), **options)))))
            return png.getpixel((10, 10)), png.getpixel((490, 10))

        self.assertEqual(corners(), (0, 255))
        self.assertEqual(corners(mirror=True), (255, 0))
        self.assertEqual(corners(invert=True), (255, 0))

    def test_dots_and_bw_are_two_tone(self):
        gray = Image.new("L", (200, 200), 128)
        for style in ("dots", "bw"):
            png = Image.open(io.BytesIO(decoded(prepare_laser(request(gray, style=style)))))
            self.assertLessEqual({value for _, value in png.getcolors()}, {0, 255}, style)

    def test_warnings(self):
        small = prepare_laser(request(half(100, 50), widthMm=300))
        self.assertTrue(any("صغيرة" in w for w in small["warnings"]))
        dark = prepare_laser(request(Image.new("L", (800, 800), 10), brightness=0))
        self.assertTrue(any("داكنة" in w for w in dark["warnings"]))

    def test_score_svg_is_centerline_in_millimetres(self):
        image = Image.new("L", (400, 200), 255)
        ImageDraw.Draw(image).line([(50, 100), (350, 100)], fill=0, width=9)
        result = prepare_laser(request(image, operation="score", widthMm=100))
        root = ET.fromstring(decoded(result))
        self.assertEqual((root.get("width"), root.get("height")), ("100.000mm", "50.000mm"))
        paths = root.findall(".//{http://www.w3.org/2000/svg}path")
        self.assertEqual(len(paths), 1)  # one centre line, not a double outline
        ys = [float(p[1:].split(",")[1]) for p in paths[0].get("d").split()]
        self.assertTrue(all(abs(y - 25) < 0.5 for y in ys))

    def test_rejects_bad_input(self):
        square = Image.new("L", (100, 100), 255)
        for extra in (
            {"material": "pvc"}, {"operation": "cut"}, {"widthMm": 400}, {"widthMm": 5},
            {"widthMm": True}, {"widthMm": float("nan")}, {"style": "x"}, {"brightness": 1.0},
            {"invert": "yes"}, {"image": "data:text/plain;base64,eA=="}, {"operation": "score"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                prepare_laser({**request(square), **extra})


if __name__ == "__main__":
    unittest.main()
