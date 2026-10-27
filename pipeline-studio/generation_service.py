"""One offline CUDA generation per process; exit releases VRAM before Lineart."""
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
ROOT = Path(__file__).resolve().parent
POST_PROCESSING = {'ink': 'opencv-adaptive-ink', 'pencil': 'opencv-graphite-pencil'}


def emit(data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


def prepare_image(settings):
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(base64.b64decode(settings['image'].split(',', 1)[1])))).convert('RGBA')
    background = Image.new('RGBA', image.size, 'white'); background.alpha_composite(image)
    return ImageOps.pad(background.convert('RGB'), (settings['resolution'], settings['resolution']),
                        method=Image.Resampling.LANCZOS, color='white')


def source_watercolor(image, strength):
    """Local paint effect from source pixels only; no diffusion, warping or colored stains."""
    import cv2
    import numpy as np
    from PIL import Image
    rgb = np.asarray(image.convert('RGB'))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    washes = cv2.stylization(bgr, sigma_s=100, sigma_r=.4)
    washes = cv2.GaussianBlur(washes, (0, 0), .65)
    original_hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hsv = cv2.cvtColor(washes, cv2.COLOR_BGR2HSV)
    # Keep source hue at each pixel: a skin region cannot turn into a red paint stain.
    hsv[:, :, 0] = original_hsv[:, :, 0]
    hsv[:, :, 1] = np.clip(original_hsv[:, :, 1].astype(np.float32) * .92, 0, 255).astype(np.uint8)
    values = hsv[:, :, 2].astype(np.float32)
    source_values = original_hsv[:, :, 2].astype(np.float32)
    hsv[:, :, 2] = np.clip(np.clip(values + 8, source_values - 28, source_values + 28), 0, 255).astype(np.uint8)
    paint = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    mixed = cv2.addWeighted(bgr, 1 - strength, paint, strength, 0)
    return Image.fromarray(cv2.cvtColor(mixed, cv2.COLOR_BGR2RGB))


def finish_style(image, style):
    if style not in ('ink', 'pencil'):
        return image
    # SDXL may keep colors despite a monochrome prompt. Remove flat fills locally.
    import cv2
    import numpy as np
    from PIL import Image
    rgb = np.asarray(image.convert('RGB'))
    if style == 'pencil':
        # Enforce actual graphite rendering even when low-strength SDXL keeps color.
        # This changes tone/strokes only; no face warping or geometric operations.
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        graphite, _ = cv2.pencilSketch(bgr, sigma_s=60, sigma_r=.07, shade_factor=.03)
        return Image.fromarray(graphite).convert('RGB')
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    smooth = cv2.bilateralFilter(gray, 9, 50, 50)
    ink = cv2.adaptiveThreshold(smooth, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 35, 8)
    return Image.fromarray(ink).convert('RGB')


def run(data):
    from generation import validate, prompts
    settings = validate(data)
    if settings['preserveSource']:
        start = time.perf_counter()
        emit({'state': 'loading', 'step': 0, 'total': 0})
        image = prepare_image(settings)
        result = source_watercolor(image, settings['strength'])
        buffer = io.BytesIO(); result.save(buffer, format='PNG')
        emit({'result': {'image': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
                         'width': result.width, 'height': result.height,
                         'seconds': round(time.perf_counter() - start, 2), 'seed': None,
                         'style': 'watercolor', 'device': 'cpu', 'model': 'OpenCV', 'engine': 'opencv',
                         'preserveSource': True, 'postProcessing': 'opencv-source-watercolor',
                         'settings': {key: settings[key] for key in ('strength', 'resolution')}}})
        return
    import torch
    from diffusers import StableDiffusionXLImg2ImgPipeline, EulerDiscreteScheduler
    from PIL import Image, ImageOps
    if not torch.cuda.is_available():
        raise ValueError('التوليد يحتاج كرت NVIDIA وبيئة CUDA المتاحة على جهازك.')
    start = time.perf_counter()
    emit({'state': 'loading', 'step': 0, 'total': 0})
    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        str(ROOT / 'models/sdxl-base-1.0'), torch_dtype=torch.float16,
        variant='fp16', use_safetensors=True, local_files_only=True,
        add_watermarker=False)
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_tiling()
    pipe.enable_vae_slicing()
    pipe.set_progress_bar_config(disable=True)
    image = prepare_image(settings)

    def progress(pipeline, step, timestep, callback_kwargs):
        emit({'state': 'running', 'step': step + 1, 'total': pipeline.num_timesteps})
        return callback_kwargs

    prompt, negative = prompts(settings)
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        result = pipe(prompt=prompt, negative_prompt=negative, image=image,
                      strength=settings['strength'], num_inference_steps=settings['steps'],
                      guidance_scale=settings['guidance'],
                      generator=torch.Generator(device='cpu').manual_seed(settings['seed']),
                      callback_on_step_end=progress).images[0]
    result = finish_style(result, settings['style'])
    buffer = io.BytesIO()
    result.save(buffer, format='PNG')
    emit({'result': {'image': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
                     'width': result.width, 'height': result.height,
                     'seconds': round(time.perf_counter() - start, 2), 'seed': settings['seed'],
                     'style': settings['style'], 'device': 'cuda', 'model': 'SDXL 1.0',
                     'engine': 'sdxl', 'preserveSource': False,
                     'postProcessing': POST_PROCESSING.get(settings['style']),
                     'settings': {key: settings[key] for key in ('strength', 'steps', 'guidance', 'resolution')},
                     'peakMiB': round(torch.cuda.max_memory_allocated() / 1048576)}})


if __name__ == '__main__':
    try:
        run(json.load(sys.stdin))
    except ValueError as error:
        emit({'error': str(error)})
        sys.exit(2)
    except Exception as error:
        message = ('ذاكرة كرت الشاشة غير كافية. أغلق النماذج الأخرى وجرّب دقة 512.'
                   if 'out of memory' in str(error).lower() else
                   'تعذر تشغيل SDXL محليًا. تحقق من اكتمال الأوزان وبيئة التوليد.')
        emit({'error': message})
        sys.exit(1)
