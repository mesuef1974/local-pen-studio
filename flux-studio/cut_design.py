"""One-piece cut design: a perforated floral ring with a name tied into it. Units: millimetres.

The name is rendered by Windows (GDI+), which shapes Arabic with the installed fonts and needs no extra library.
"""
import base64
import io
import math
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

S = 30  # pixels per design millimetre
SIDE = int(136 * S)
C = SIDE // 2
IN, OUT = 45.0, 53.0
MID = (IN + OUT) / 2
NECK = 1.6
REACH = 2.5  # how far the name's outermost strokes enter the ring
TOUCH = 0.6  # gap left between name parts before thickening, so dots touch yet stay readable
FONTS = ('Aldhabi', 'DecoType Thuluth', 'Andalus', 'Sakkal Majalla', 'Traditional Arabic')
SIZE_MM = (80, 280)  # longest side of the finished piece
MAX_NAME = 30

# Text and font travel as code points, so nothing the user types is read as PowerShell.
RENDER = r'''$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$word = -join ([char[]]@(__TEXT__))
$family = New-Object System.Drawing.FontFamily '__FONT__'
$style = [System.Drawing.FontStyle]::Regular
if ('__FONT__' -eq 'Sakkal Majalla') { $style = [System.Drawing.FontStyle]::Bold }
$format = New-Object System.Drawing.StringFormat
$format.FormatFlags = [System.Drawing.StringFormatFlags]__FLAGS__
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.FillMode = 'Winding'
$path.AddString($word, $family, [int]$style, 900, (New-Object System.Drawing.PointF 0, 0), $format)
$box = $path.GetBounds()
$bmp = New-Object System.Drawing.Bitmap ([int]$box.Width + 100), ([int]$box.Height + 100)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$g.SmoothingMode = 'AntiAlias'
$g.TranslateTransform(50 - $box.X, 50 - $box.Y)
$g.FillPath([System.Drawing.Brushes]::Black, $path)
$bmp.Save('__OUT__')
'''


def clean_name(text):
    if not isinstance(text, str):
        raise ValueError('اكتب الاسم.')
    text = ' '.join(unicodedata.normalize('NFC', text).split())
    if not 0 < len(text) <= MAX_NAME:
        raise ValueError(f'الاسم من حرف إلى {MAX_NAME} حرفًا.')
    if any(unicodedata.category(c)[0] not in 'LMNPZ' for c in text):
        raise ValueError('الاسم يقبل الحروف والأرقام وعلامات الترقيم فقط.')
    return text


def render_name(text, font):
    """Ink mask (255 = name) cropped to the glyphs."""
    if font not in FONTS:
        raise ValueError('الخط غير متاح.')
    if sys.platform != 'win32':
        raise ValueError('كتابة الاسم تعمل على Windows فقط.')
    rtl = any(unicodedata.bidirectional(c) in ('R', 'AL') for c in text)
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / 'name.png'
        script = (RENDER.replace('__TEXT__', ','.join(str(u) for u in memoryview(text.encode('utf-16-le')).cast('H')))
                  .replace('__FONT__', font).replace('__FLAGS__', '1' if rtl else '0')
                  .replace('__OUT__', str(out).replace("'", "''")))
        command = ['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                   base64.b64encode(script.encode('utf-16-le')).decode()]
        done = subprocess.run(command, capture_output=True, timeout=60)
        if done.returncode or not out.is_file():
            raise ValueError('تعذرت كتابة الاسم بهذا الخط؛ تأكد أنه مثبَّت في Windows.')
        with Image.open(out) as image:
            ink = (np.array(image.convert('L')) < 128).astype(np.uint8) * 255
    ys, xs = np.nonzero(ink)
    if not len(xs):
        raise ValueError('هذا الخط لا يرسم هذه الحروف.')
    return ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def px(p):
    return int(round(C + p[0] * S)), int(round(C + p[1] * S))


def unit(angle):
    a = math.radians(angle)
    return np.array([math.cos(a), math.sin(a)])


def line(image, points, width, value=255):
    cv2.polylines(image, [np.array([px(p) for p in points])], False, value, int(width * S), cv2.LINE_AA)


def smooth(points, n=14):
    """Catmull-Rom through a closed list of points."""
    out = []
    m = len(points)
    for i in range(m):
        p0, p1, p2, p3 = (points[(i + k - 1) % m] for k in range(4))
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    return np.array(out)


def fill(image, points):
    cv2.fillPoly(image, [np.array([px(p) for p in points])], 255, cv2.LINE_AA)


def leaf(mask, base, direction, length, width):
    along = unit(direction)
    across = np.array([-along[1], along[0]])
    t = np.linspace(0, 1, 80)
    half = width / 2 * np.sin(math.pi * t ** 0.8) ** 0.9
    spine = base + np.outer(t * length, along) + np.outer(np.sin(math.pi * t) * length * 0.06, across)
    outline = np.vstack([spine + np.outer(half, across), (spine - np.outer(half, across))[::-1]])
    # A thin cut around each leaf keeps overlapping leaves readable.
    for side in (outline[26:80], outline[80:134]):
        line(mask, side, 1.0, 0)
    fill(mask, outline)
    if length > 11:
        line(mask, spine[22:62], 0.7, 0)


def flower(mask, centre, radius, turn, tie):
    petals = []
    for k in range(5):
        u = unit(turn + 72 * k)
        v = np.array([-u[1], u[0]])
        petals.append(smooth(np.array([centre + u * r * radius + v * s * radius for r, s in (
            (0.15, 0.10), (0.45, 0.31), (0.72, 0.43), (0.93, 0.37), (1.02, 0.20), (0.92, 0.0),
            (1.02, -0.20), (0.93, -0.37), (0.72, -0.43), (0.45, -0.31), (0.15, -0.10))])))
    large = radius > 10
    # A clear cut all around the flower, then the stem is laid back across it as the tie.
    for shape in petals:
        cv2.polylines(mask, [np.array([px(p) for p in shape])], True, 0, int((2.2 if large else 1.6) * S), cv2.LINE_AA)
    line(mask, [unit(a) * MID for a in np.linspace(tie - 17, tie + 17, 60)], 3.0)
    for shape in petals:
        fill(mask, shape)
    cv2.circle(mask, px(centre), int(radius * 0.40 * S), 255, -1, cv2.LINE_AA)
    cv2.circle(mask, px(centre), int(radius * 0.20 * S), 0, -1, cv2.LINE_AA)
    for k in range(5 if large else 0):
        u = unit(turn + 72 * k + 36)
        line(mask, [centre + u * radius * 0.34, centre + u * radius * 0.80], 1.0, 0)
        v = unit(turn + 72 * k)
        line(mask, [centre + v * radius * 0.34, centre + v * radius * 0.62], 0.9, 0)


def floral_ring():
    mask = np.zeros((SIDE, SIDE), np.uint8)
    cv2.circle(mask, (C, C), int(OUT * S), 255, -1, cv2.LINE_AA)
    cv2.circle(mask, (C, C), int(IN * S), 0, -1, cv2.LINE_AA)
    for angle in np.arange(0, 360, 7.8):
        cv2.circle(mask, px(unit(angle) * MID), int(2.2 * S), 0, -1, cv2.LINE_AA)
    cv2.circle(mask, (C, C), int((IN + 1.2) * S), 255, int(2.4 * S), cv2.LINE_AA)
    for centre in (-112, 68):
        line(mask, [unit(a) * MID for a in np.linspace(centre - 40, centre + 40, 80)], 2.6)
    for centre in (-112, 68):
        for sweep in (-1, 1):
            # (offset from the flower in degrees, lean away from the band, length, width, radial start)
            for offset, lean, length, width, radius in (
                    (39, 14, 13, 6.2, MID), (30, -34, 11, 5.4, MID - 1), (23, 40, 15, 7.2, MID + 1),
                    (15, -22, 14, 6.8, MID - 2), (11, 58, 13, 6.4, MID + 2)):
                angle = centre + sweep * offset
                base = unit(angle) * radius
                direction = angle + sweep * 90 - sweep * lean
                excess = np.linalg.norm(base + unit(direction) * length) - 62
                leaf(mask, base, direction, length - max(excess, 0), width)
    for centre in (-112, 68):
        line(mask, [unit(a) * (MID - 0.6) for a in np.linspace(centre - 38, centre + 38, 90)], 3.2)
    flower(mask, unit(-80) * (MID + 1), 7.0, 20, -80)
    flower(mask, unit(101) * (MID + 1), 6.5, 50, 101)
    flower(mask, unit(-112) * (MID + 1.5), 13.5, -112, -112)
    flower(mask, unit(68) * (MID + 1.5), 12.5, 68, 68)
    return mask


def gather(ink, overlap):
    """Slide every loose dot or letter towards the rest of the name; negative overlap leaves a gap."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats((ink > 127).astype(np.uint8), 8)
    if count <= 2:
        return ink
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    body = np.where(labels == main, 255, 0).astype(np.uint8)
    loose = {i: np.column_stack(np.nonzero(labels == i)) for i in range(1, count) if i != main}
    while loose:
        distance, nearest = cv2.distanceTransformWithLabels(255 - body, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        part = min(loose, key=lambda i: distance[loose[i][:, 0], loose[i][:, 1]].min())
        points = loose.pop(part)
        gaps = distance[points[:, 0], points[:, 1]]
        start = points[int(np.argmin(gaps))]
        targets = np.column_stack(np.nonzero(body))
        end = targets[nearest[start[0], start[1]] - 1]
        step = end - start
        length = float(np.hypot(*step))
        moved = points + np.round(step * (1 + overlap / max(length, 1))).astype(int)
        moved = np.clip(moved, 0, np.array(body.shape) - 1)
        body[moved[:, 0], moved[:, 1]] = 255
    return body


def place_name(word):
    """The name made one body, thickened, and sized so its outermost strokes enter the ring by themselves."""
    unit_px = 86 * S / word.shape[1] if word.shape[1] >= word.shape[0] else 86 * S / word.shape[0]
    size = max(1, int(word.shape[1] * unit_px)), max(1, int(word.shape[0] * unit_px))
    word = np.pad(cv2.resize(word, size, interpolation=cv2.INTER_AREA), 20 * S)
    word = gather(word, -TOUCH * S)
    ys, xs = np.nonzero(word > 127)
    (cx, cy), radius = cv2.minEnclosingCircle(cv2.convexHull(np.column_stack([xs, ys]).astype(np.int32)))
    # The thickening below adds 0.55 mm all round.
    scale = (IN + REACH - 0.55) * S / radius
    matrix = np.float32([[scale, 0, C - cx * scale], [0, scale, C - cy * scale]])
    layer = cv2.warpAffine(word, matrix, (SIDE, SIDE), flags=cv2.INTER_LINEAR)
    return cv2.dilate(layer, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(1.1 * S) | 1,) * 2))


def bridge(solid):
    """Join every loose part to the body; crumbs under 3×3 mm are dropped. Returns the number of struts."""
    added = 0
    while True:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
        if count <= 2:
            return added
        main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        loose = next(i for i in range(1, count) if i != main)
        if stats[loose, cv2.CC_STAT_AREA] < (3.0 * S) ** 2:
            solid[labels == loose] = 0
            continue
        distance, nearest = cv2.distanceTransformWithLabels((labels != main).astype(np.uint8), cv2.DIST_L2, 5,
                                                            labelType=cv2.DIST_LABEL_PIXEL)
        py, qx = np.nonzero(labels == loose)
        best = int(np.argmin(distance[py, qx]))
        start = (int(qx[best]), int(py[best]))
        zy, zx = np.nonzero(labels == main)
        index = nearest[start[1], start[0]] - 1
        end = (int(zx[index]), int(zy[index]))
        direction = np.subtract(end, start) / max(math.dist(start, end), 1)
        a = tuple(int(v) for v in np.subtract(start, direction * 1.4 * S))
        b = tuple(int(v) for v in np.add(end, direction * 1.4 * S))
        cv2.line(solid, a, b, 1, int(2.2 * S))
        added += 1


def reinforce(solid):
    """Widen anything held only by a neck thinner than NECK. Returns how many parts are still weak."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(NECK * S) | 1,) * 2)
    for attempt in range(5):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.erode(solid, kernel), 8)
        if count <= 2:
            return 0
        body = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        loose = [i for i in range(1, count) if i != body and stats[i, cv2.CC_STAT_AREA] > 4 * S ** 2]
        if not loose or attempt == 4:
            return len(loose)
        distance, nearest = cv2.distanceTransformWithLabels((labels != body).astype(np.uint8), cv2.DIST_L2, 5,
                                                            labelType=cv2.DIST_LABEL_PIXEL)
        zy, zx = np.nonzero(labels == body)
        for i in loose:
            qy, qx = np.nonzero(labels == i)
            best = int(np.argmin(distance[qy, qx]))
            index = nearest[qy[best], qx[best]] - 1
            cv2.line(solid, (int(qx[best]), int(qy[best])), (int(zx[index]), int(zy[index])), 1, int(2.6 * S))


def compose(word, size_mm=120):
    """Build the piece from a name ink mask."""
    mask = floral_ring()
    np.maximum(mask, place_name(word), out=mask)

    solid = (cv2.GaussianBlur(mask, (9, 9), 0) > 127).astype(np.uint8)
    # Slits narrower than the cut can resolve are closed.
    solid = cv2.morphologyEx(solid, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.5 * S) | 1,) * 2))
    struts = bridge(solid)
    found, hierarchy = cv2.findContours(solid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    for i, contour in enumerate(found):
        if hierarchy[0][i][3] >= 0 and cv2.contourArea(contour) < (1.6 * S) ** 2:
            cv2.drawContours(solid, [contour], -1, 1, -1)
    weak = reinforce(solid)
    pieces = cv2.connectedComponents(solid, connectivity=8)[0] - 1

    contours, _ = cv2.findContours(solid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    shapes = [cv2.approxPolyDP(c, 1.2, True)[:, 0, :] / S for c in contours]
    every = np.vstack(shapes)
    low, size = every.min(axis=0), every.max(axis=0) - every.min(axis=0)
    scale = size_mm / size.max()
    shapes = [(shape - low) * scale for shape in shapes]
    width, height = size * scale

    def svg(mirror):
        parts = []
        for points in shapes:
            if mirror:
                points = np.column_stack([width - points[:, 0], points[:, 1]])
            parts.append('M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in points) + ' Z')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" '
                f'viewBox="0 0 {width:.3f} {height:.3f}"><path fill="none" stroke="#ff0000" stroke-width="0.1" '
                f'd="{" ".join(parts)}"/></svg>\n')

    preview = np.full((SIDE, SIDE, 3), (240, 236, 232), np.uint8)
    preview[np.roll(solid, (25, 25), axis=(0, 1)) > 0] = (200, 192, 185)
    shade = np.linspace(0, 1, SIDE)[:, None, None]
    rose = (np.array((232, 190, 165)) * (1 - shade) + np.array((170, 115, 90)) * shade).astype(np.uint8)
    preview = np.where(solid[:, :, None] > 0, np.broadcast_to(rose, preview.shape), preview).astype(np.uint8)
    png = io.BytesIO()
    Image.fromarray(cv2.resize(preview, (900, 900), interpolation=cv2.INTER_AREA)).save(png, 'PNG')
    return {'svg': svg(False), 'mirroredSvg': svg(True),
            'preview': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode(),
            'widthMm': round(float(width), 1), 'heightMm': round(float(height), 1),
            'holes': len(shapes) - 1, 'pieces': int(pieces), 'weakParts': int(weak), 'struts': struts}


def design(data):
    """Validate a request from the page and build the piece."""
    name = clean_name(data.get('name'))
    size = data.get('sizeMm', 120)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not SIZE_MM[0] <= size <= SIZE_MM[1]:
        raise ValueError(f'المقاس من {SIZE_MM[0]} إلى {SIZE_MM[1]} مم.')
    return compose(render_name(name, data.get('font', FONTS[0])), float(size))
