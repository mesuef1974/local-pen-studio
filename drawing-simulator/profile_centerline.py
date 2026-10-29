"""Repeatable, opt-in centerline stage profile with physical-pen fidelity metrics."""
import argparse
import base64
import hashlib
import io
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DRAW = ROOT / "drawing-simulator"
sys.path.insert(0, str(DRAW))
from pen_paths import extract_paths as current_extract_paths

DEFAULT_IMAGES = [
    ROOT / "flux-studio" / "sample-ink.png",
    DRAW / "reference-benchmark" / "reference.png",
]


def load_baseline_extractor(ref):
    source = subprocess.check_output(
        ["git", "show", f"{ref}:drawing-simulator/pen_paths.py"],
        cwd=ROOT, text=True, encoding="utf-8")
    source = instrument_baseline_source(source)
    namespace = {"__name__": "pen_paths_profile_baseline",
                 "__file__": str(DRAW / "pen_paths.py")}
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    return namespace["extract_paths"]


def instrument_baseline_source(source):
    """Add opt-in stage timers to the immutable baseline source for fair profiling."""
    replacements = [
        ("import base64, binascii, io, math\n", "import base64, binascii, io, math, time\n"),
        ("def extract_paths(data):\n    encoded=data.get('image','')\n", """def extract_paths(data):
    profile_enabled=data.get('profileTimings',False)
    total_started=time.perf_counter();stage_started=total_started;timings={}
    def mark(stage):
        nonlocal stage_started
        now=time.perf_counter()
        if profile_enabled:timings[stage]=round((now-stage_started)*1000,3)
        stage_started=now
    encoded=data.get('image','')
"""),
        ("    except (OSError,UnidentifiedImageError):raise ValueError('تعذر قراءة المصدر.')\n", "    except (OSError,UnidentifiedImageError):raise ValueError('تعذر قراءة المصدر.')\n    mark('input_decode_and_validation')\n"),
        ("    if smoothing:gray=cv2.bilateralFilter(gray,9,float(smoothing),25)\n", "    if smoothing:gray=cv2.bilateralFilter(gray,9,float(smoothing),25)\n    mark('grayscale_and_denoise')\n"),
        ("detector.detectEdges(gray)\n    segments=detector.getSegments()\n", "detector.detectEdges(gray)\n    segments=detector.getSegments()\n    mark('edge_detection')\n"),
        ("        _,binary=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY_INV+(cv2.THRESH_OTSU if threshold==0 else 0))\n", "        _,binary=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY_INV+(cv2.THRESH_OTSU if threshold==0 else 0))\n        mark('threshold')\n"),
        ("        skeleton=cv2.ximgproc.thinning(binary)\n", "        skeleton=cv2.ximgproc.thinning(binary)\n        mark('thinning')\n"),
        ("        ys,xs=np.where(skeleton>0);nodes=", "        graph_started=time.perf_counter()\n        ys,xs=np.where(skeleton>0);nodes="),
        ("        visited=set();segments=[]\n", "        mark('graph_construction')\n        visited=set();segments=[]\n"),
        ("        routing=data.get('junctionRouting',True)\n", "        timings['graph_trace']=round((time.perf_counter()-stage_started)*1000,3) if profile_enabled else 0\n        mark('graph_trace')\n        routing=data.get('junctionRouting',True)\n"),
        ("            segments,routing_stats=route_junctions(segments)\n", "            segments,routing_stats=route_junctions(segments)\n        mark('junction_routing')\n"),
        ("    if len(result)>6000:raise ValueError('الصورة شديدة التعقيد؛ خفّف الضوضاء أو قلل التفاصيل.')\n    return {", "    if len(result)>6000:raise ValueError('الصورة شديدة التعقيد؛ خفّف الضوضاء أو قلل التفاصيل.')\n    mark('path_simplification_and_limits')\n    output={"),
        ("'outputPoints':sum(len(p) for p in result),**routing_stats}\n", """'outputPoints':sum(len(p) for p in result),**routing_stats}
    if profile_enabled:
        timings['total']=round((time.perf_counter()-total_started)*1000,3)
        output['profileTimingsMs']=timings
    return output
"""),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(f"Baseline profiler expected one source marker, found {source.count(old)}: {old[:60]!r}")
        source = source.replace(old, new, 1)
    return source


def encode_png(path):
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        pixels = np.asarray(image.convert("RGB"))
    url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    return pixels, url, hashlib.sha256(raw).hexdigest()


def summarize(path, repeats, extractor, implementation):
    rgb, url, digest = encode_png(path)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    skeleton = cv2.ximgproc.thinning(ink) > 0
    options = {"image": url, "lineMode": "centerline", "lineDenoise": 0,
               "inkThreshold": 0, "tolerance": 0, "minLength": 2,
               "componentMin": 0, "spurLength": 0, "junctionRouting": True,
               "profileTimings": True}
    runs = []
    outputs = []
    for _ in range(repeats):
        started = time.perf_counter()
        result = extractor(options)
        wall_ms = (time.perf_counter() - started) * 1000
        runs.append({"wallMs": wall_ms, **result.get("profileTimingsMs", {})})
        outputs.append(result)

    last = outputs[-1]
    raster = np.zeros(skeleton.shape, np.uint8)
    for points in last["paths"]:
        if len(points) >= 2:
            cv2.polylines(raster, [np.asarray(points, np.int32)], False, 255, 1, cv2.LINE_8)
    both = int(np.count_nonzero(skeleton & (raster > 0)))
    target_count = int(np.count_nonzero(skeleton))
    raster_count = int(np.count_nonzero(raster))
    union = target_count + raster_count - both
    stage_names = sorted({key for run in runs for key in run if key != "wallMs"})
    stages = {key: round(statistics.median(run[key] for run in runs if key in run), 3)
              for key in stage_names}
    return {
        "name": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
        "sha256": digest,
        "width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
        "skeletonPixels": target_count,
        "repeats": repeats,
        "implementation": implementation,
        "medianStagesMs": stages,
        "medianWallMs": round(statistics.median(run["wallMs"] for run in runs), 3),
        "pathCount": len(last["paths"]), "pointCount": last["outputPoints"],
        "centerlineRasterSha256": hashlib.sha256(raster.tobytes()).hexdigest(),
        "centerlineVsSkeleton": {
            "inkIoUPercent": round(100 * both / union, 5) if union else 100.0,
            "inkRecallPercent": round(100 * both / target_count, 5) if target_count else 100.0,
            "inkPrecisionPercent": round(100 * both / raster_count, 5) if raster_count else 100.0,
            "rasterPixels": raster_count,
        },
        "physicalPenAudit": physical_audit(url, last["paths"]),
    }


def physical_audit(image_url, paths):
    sys.path.insert(0, str(ROOT / "flux-studio"))
    from path_fidelity import audit
    result = audit({"image": image_url, "paths": paths,
                    "mmPerPixel": 0.2, "penMm": 0.3, "inkThreshold": 0})
    return {key: result[key] for key in
            ("inkIoU", "inkRecall", "inkPrecision", "missingInkPercent", "extraInkPercent")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path,
                        help="PNG inputs; defaults to two committed line-art samples")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--implementation", choices=("baseline", "current"), default="current")
    parser.add_argument("--baseline-ref", default="HEAD",
                        help="Git ref used by --implementation baseline")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    if args.repeats < 3 or args.repeats > 20:
        parser.error("--repeats must be between 3 and 20")
    images = [path.resolve() for path in args.images] if args.images else DEFAULT_IMAGES
    extractor = (load_baseline_extractor(args.baseline_ref)
                 if args.implementation == "baseline" else current_extract_paths)
    report = {
        "schema": "centerline-stage-profile-v1",
        "python": platform.python_version(), "opencv": cv2.__version__,
        "numpy": np.__version__, "platform": platform.platform(),
        "implementation": args.implementation,
        "baselineRef": args.baseline_ref if args.implementation == "baseline" else None,
        "method": "centerline; Otsu threshold; denoise=0; no spur pruning; no simplification; junction routing enabled",
        "timing": "median of repeated end-to-end calls; includes image decode and extractor setup",
        "physicalPen": {"diameterMm": 0.3, "mmPerPixel": 0.2,
                        "fidelityRenderer": "CairoSVG physical-pen mask audit"},
        "samples": [summarize(path, args.repeats, extractor, args.implementation)
                    for path in images],
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
