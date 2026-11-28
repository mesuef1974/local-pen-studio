"""Image to laser-ready file for xTool P2S: raster PNG (engrave) or SVG lines (score).

Geometry and tone only. Power, speed and focus are chosen in the machine software.
"""
import base64
import binascii
import io
import math

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

PX_PER_MM = 10  # 254 DPI
BED_MM = (600, 305)
MIN_MM = 10
MATERIALS = ("wood", "acrylic")
OPERATIONS = ("engrave", "score")
STYLES = ("gray", "dots", "bw")
GAMMA = {0: 1.0, 1: 0.75, 2: 0.55}


def _decode(encoded):
    prefixes = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")
    if not isinstance(encoded, str) or not encoded.startswith(prefixes):
        raise ValueError("صيغة الصورة غير مناسبة.")
    try:
        raw = base64.b64decode(encoded.split(",", 1)[1], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("بيانات الصورة غير صحيحة.")
    if not 0 < len(raw) <= 5_000_000:
        raise ValueError("الصورة أكبر من الحد.")
    try:
        with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as source:
            if source.width * source.height > 4_000_000:
                raise ValueError("الصورة تتجاوز أربعة ملايين بكسل.")
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, UnidentifiedImageError):
        raise ValueError("تعذر قراءة الصورة.")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    return background.convert("L")


def _size(width_mm, image):
    if isinstance(width_mm, bool) or not isinstance(width_mm, (int, float)) or not math.isfinite(width_mm):
        raise ValueError("أدخل العرض بالمليمتر.")
    height_mm = width_mm * image.height / image.width
    if not (MIN_MM <= width_mm <= BED_MM[0] and MIN_MM <= height_mm <= BED_MM[1]):
        raise ValueError(
            f"المقاس {width_mm:g}×{height_mm:.1f} مم خارج الحد: من {MIN_MM} مم "
            f"إلى {BED_MM[0]}×{BED_MM[1]} مم."
        )
    return float(width_mm), height_mm


def _data_url(mime, raw):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _png(image, **options):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **options)
    return buffer.getvalue()


def _otsu(values):
    histogram = np.bincount(values.ravel(), minlength=256).astype(float)
    weight = np.cumsum(histogram)
    mean = np.cumsum(histogram * np.arange(256))
    spread = weight * (weight[-1] - weight)
    between = np.divide((mean[-1] * weight - mean * weight[-1]) ** 2, spread,
                        out=np.zeros(256), where=spread > 0)
    return int(np.argmax(between))


def _engrave(image, width_mm, height_mm, data):
    style = data.get("style", "gray")
    brightness = data.get("brightness", 1)
    invert = data.get("invert", False)
    mirror = data.get("mirror", False)
    if style not in STYLES:
        raise ValueError("أسلوب النقش غير معروف.")
    if type(brightness) is not int or brightness not in GAMMA:
        raise ValueError("درجة التفتيح غير صحيحة.")
    if not isinstance(invert, bool) or not isinstance(mirror, bool):
        raise ValueError("خيار العكس غير صحيح.")
    size = (round(width_mm * PX_PER_MM), round(height_mm * PX_PER_MM))
    out = image.resize(size, Image.Resampling.LANCZOS)
    gamma = GAMMA[brightness]
    out = out.point([round(255 * (v / 255) ** gamma) for v in range(256)])
    dark = float((np.asarray(out) < 64).mean())
    if style == "dots":
        out = out.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    elif style == "bw":
        threshold = _otsu(np.asarray(out))
        out = out.point([0 if v <= threshold else 255 for v in range(256)])
    if invert:
        out = ImageOps.invert(out)
    if mirror:
        out = ImageOps.mirror(out)
    warnings = []
    if dark > 0.4:
        warnings.append("مساحات واسعة داكنة قد تخرج بقعة واحدة. جرّب تفتيحًا أعلى.")
    png = _png(out, dpi=(PX_PER_MM * 25.4, PX_PER_MM * 25.4))
    url = _data_url("image/png", png)
    return {"preview": url, "file": url, "extension": "png"}, warnings


def _score(image, width_mm, height_mm):
    from pen_paths import extract_paths

    midtones = float(((np.asarray(image) > 60) & (np.asarray(image) < 200)).mean())
    traced = extract_paths({
        "image": _data_url("image/png", _png(image)),
        "lineMode": "centerline", "lineDenoise": 0, "minLength": 8, "tolerance": 0.6,
    })
    if not traced["paths"]:
        raise ValueError("لم أجد خطوطًا. استعمل رسمًا أسود على خلفية بيضاء.")
    sx = width_mm / traced["width"]
    sy = height_mm / traced["height"]
    body = "".join(
        '<path d="' + " ".join(
            f"{'L' if i else 'M'}{x * sx:.3f},{y * sy:.3f}" for i, (x, y) in enumerate(path)
        ) + '"/>'
        for path in traced["paths"]
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" '
        f'viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">'
        f'<g fill="none" stroke="#ff0000" stroke-width="0.1">{body}</g></svg>'
    )
    warnings = []
    if midtones > 0.15:
        warnings.append("الصورة ليست رسمًا خطيًا واضحًا. حوّلها إلى خطوط في «مسار» أولًا.")
    url = _data_url("image/svg+xml", svg.encode())
    # The file keeps hairlines; the on-screen preview needs a stroke the eye can see.
    shown = svg.replace('stroke-width="0.1"', f'stroke-width="{max(width_mm, height_mm) / 400:.3f}"')
    return {"preview": _data_url("image/svg+xml", shown.encode()), "file": url,
            "extension": "svg", "paths": len(traced["paths"])}, warnings


def prepare_laser(data):
    material = data.get("material")
    operation = data.get("operation")
    if material not in MATERIALS:
        raise ValueError("اختر الخامة: خشب أو أكريليك.")
    if operation not in OPERATIONS:
        raise ValueError("اختر العملية: نقش أو خطوط.")
    image = _decode(data.get("image"))
    width_mm, height_mm = _size(data.get("widthMm"), image)
    source_dpi = image.width / (width_mm / 25.4)
    if operation == "engrave":
        result, warnings = _engrave(image, width_mm, height_mm, data)
    else:
        result, warnings = _score(image, width_mm, height_mm)
    if source_dpi < 150:
        warnings.insert(0, "الصورة صغيرة لهذا المقاس وقد تبدو مشوشة. صغّر المقاس أو ارفع صورة أكبر.")
    result.update(
        widthMm=round(width_mm, 1), heightMm=round(height_mm, 1),
        sourceDpi=round(source_dpi), warnings=warnings,
        name=f"masar-{material}-{operation}-{round(width_mm)}x{round(height_mm)}mm.{result['extension']}",
    )
    return result
