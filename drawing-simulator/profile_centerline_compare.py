"""Paired baseline/current centerline timing and output-fidelity comparison."""
import argparse
import hashlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from profile_centerline import DEFAULT_IMAGES, ROOT, load_baseline_extractor, physical_audit
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineart_processing import encode
from pen_paths import extract_paths


def render_paths(paths, shape):
    raster = np.zeros(shape, np.uint8)
    for line in paths:
        if len(line) >= 2:
            cv2.polylines(raster, [np.asarray(line, np.int32)], False, 255, 1, cv2.LINE_8)
    return raster


def compare_sample(path, repeats, baseline, current):
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        rgb = np.asarray(source.convert("RGB"))
    image_url = encode(rgb)
    options = {"image": image_url, "lineMode": "centerline", "lineDenoise": 0,
               "inkThreshold": 0, "tolerance": 0, "minLength": 2,
               "componentMin": 0, "spurLength": 0, "junctionRouting": True,
               "profileTimings": True}
    baseline(options)
    current(options)
    runs = {"baseline": [], "current": []}
    stage_runs = {"baseline": [], "current": []}
    results = {}
    for index in range(repeats):
        order = (("baseline", baseline), ("current", current)) if index % 2 == 0 else (("current", current), ("baseline", baseline))
        for name, extractor in order:
            started = time.perf_counter()
            results[name] = extractor(options)
            runs[name].append((time.perf_counter() - started) * 1000)
            stage_runs[name].append(results[name].get("profileTimingsMs", {}))
    rasters = {name: render_paths(result["paths"], rgb.shape[:2])
               for name, result in results.items()}
    hashes = {name: hashlib.sha256(raster.tobytes()).hexdigest()
              for name, raster in rasters.items()}
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    skeleton = cv2.ximgproc.thinning(binary) > 0
    raster_mask = rasters["current"] > 0
    intersection = int(np.count_nonzero(skeleton & raster_mask))
    target_pixels = int(np.count_nonzero(skeleton))
    raster_pixels = int(np.count_nonzero(raster_mask))
    union = target_pixels + raster_pixels - intersection
    medians = {name: round(statistics.median(times), 3)
               for name, times in runs.items()}
    median_stages = {}
    for implementation, samples in stage_runs.items():
        stage_names = sorted({key for run in samples for key in run})
        median_stages[implementation] = {
            key: round(statistics.median(run[key] for run in samples if key in run), 3)
            for key in stage_names
        }
    return {
        "name": path.relative_to(ROOT).as_posix(),
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
        "repeatsPerImplementation": repeats,
        "order": "alternating baseline/current order each repetition after one warm-up call each",
        "medianWallMs": medians,
        "currentSpeedupPercent": round(100 * (medians["baseline"] - medians["current"]) / medians["baseline"], 2),
        "pathCount": {name: len(result["paths"]) for name, result in results.items()},
        "centerlineRasterSha256": hashes,
        "exactRasterMatch": hashes["baseline"] == hashes["current"],
        "centerlineVsSkeleton": {
            "inkIoUPercent": round(100 * intersection / union, 5) if union else 100.0,
            "inkRecallPercent": round(100 * intersection / target_pixels, 5) if target_pixels else 100.0,
            "inkPrecisionPercent": round(100 * intersection / raster_pixels, 5) if raster_pixels else 100.0,
            "skeletonPixels": target_pixels,
            "rasterPixels": raster_pixels,
        },
        "physicalPenAudit": physical_audit(image_url, results["current"]["paths"]),
        "medianStagesMs": median_stages,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--baseline-ref", default="36058c65d368ee307965c7742f752b446c6cac6f")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 5 <= args.repeats <= 30:
        parser.error("--repeats must be between 5 and 30")
    baseline = load_baseline_extractor(args.baseline_ref)
    paths = [path.resolve() for path in args.images] if args.images else DEFAULT_IMAGES
    report = {
        "schema": "paired-centerline-baseline-current-v1",
        "baselineRef": args.baseline_ref,
        "environment": {"python": sys.version.split()[0], "opencv": cv2.__version__,
                        "numpy": np.__version__},
        "method": "paired end-to-end extraction; input decode included; graph stages from current extractor profile; fidelity is exact raster hash comparison",
        "samples": [compare_sample(path, args.repeats, baseline, extract_paths) for path in paths],
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
