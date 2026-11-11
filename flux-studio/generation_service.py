"""Raw local FLUX image editing worker. No style filters or SDXL fallback.

Reads one JSON job per stdin line and keeps the model loaded between jobs.
"""
import base64
import gc
import io
import json
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
ROOT = Path(__file__).resolve().parent


def emit(event):
    print(json.dumps(event, ensure_ascii=True), flush=True)


def prompt_token_count(tokenizer, prompt):
    # Transformers versions may return a BatchEncoding for tokenize=True.
    # Count the token IDs themselves, including the same chat template as inference.
    text = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False)
    return len(tokenizer(text, truncation=False)['input_ids'])


class Engine:
    """Loaded once per worker process and reused by every job the process serves."""

    def __init__(self):
        self.tokenizer = None
        self.pipe = None
        self.text_encoder = None
        self.embeds = OrderedDict()

    def load(self):
        import torch
        from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel, GGUFQuantizationConfig
        from setup_flux import MODEL_DIR, QUANT_FILE
        transformer = Flux2Transformer2DModel.from_single_file(
            str(MODEL_DIR / QUANT_FILE), config=str(MODEL_DIR), subfolder='transformer',
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
            dtype=torch.bfloat16, local_files_only=True)
        pipe = Flux2KleinPipeline.from_pretrained(str(MODEL_DIR), transformer=transformer, tokenizer=self.tokenizer,
            dtype=torch.bfloat16, local_files_only=True)
        # Recursive meta hooks from Accelerate discard GGUF quantization metadata.
        # Offload only the unquantized text encoder: its weights stay in RAM and visit
        # the GPU layer by layer, so it never competes with image inference for VRAM.
        from accelerate import cpu_offload
        cpu_offload(pipe.text_encoder, execution_device=torch.device('cuda'))
        self.text_encoder = pipe.text_encoder
        pipe.text_encoder = None  # keep pipe.to('cuda') away from the offloaded encoder
        pipe.to('cuda')
        pipe.vae.enable_tiling()
        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe

    def encode(self, prompt):
        import torch
        if prompt in self.embeds:
            self.embeds.move_to_end(prompt)
            return self.embeds[prompt]
        self.pipe.text_encoder = self.text_encoder
        try:
            with torch.inference_mode():
                embeds, _ = self.pipe.encode_prompt(prompt, device=torch.device('cuda'))
        finally:
            self.pipe.text_encoder = None
        self.embeds[prompt] = embeds
        while len(self.embeds) > 4:
            self.embeds.popitem(last=False)
        return embeds

    def generate(self, data):
        from generation import validate, prompts, dimensions, image_bytes, IMAGE_FORMATS
        from setup_flux import MODEL_DIR
        from PIL import Image, ImageOps
        settings = validate(data)
        import torch
        if not torch.cuda.is_available():
            raise ValueError('تشغيل FLUX يحتاج إتاحة كرت NVIDIA على الجهاز.')
        started = time.perf_counter()
        emit({'state': 'loading', 'step': 0, 'total': 0})
        if self.tokenizer is None:
            from transformers import Qwen2TokenizerFast
            self.tokenizer = Qwen2TokenizerFast.from_pretrained(str(MODEL_DIR / 'tokenizer'), local_files_only=True)
        prompt = prompts(settings)
        token_count = prompt_token_count(self.tokenizer, prompt)
        if token_count > 512:
            raise ValueError('الوصف والتوجيهات تتجاوز 512 رمزًا. اختصر الوصف أو قلّل التوجيهات؛ لم يُقص النص تلقائيًا.')
        warm = self.pipe is not None
        if not warm:
            self.load()
        torch.cuda.reset_peak_memory_stats()
        prompt_embeds = self.encode(prompt)
        images = []
        if settings['mode'] != 'generate':
            for encoded in [settings['image']] + [ref['image'] for ref in settings['references']]:
                image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes(encoded)), formats=IMAGE_FORMATS)).convert('RGBA')
                canvas = Image.new('RGBA', image.size, 'white')
                canvas.alpha_composite(image)
                # Reference frames keep their own aspect ratio; only the output uses aspect.
                ref_width, ref_height = dimensions(settings | {'aspect': 'source'}, image.size)
                images.append(canvas.convert('RGB').resize((ref_width, ref_height), Image.Resampling.LANCZOS))
        width, height = dimensions(settings, images[0].size if images else None)

        def progress(pipeline, step, timestep, kwargs):
            emit({'state': 'running', 'step': step + 1, 'total': 4})
            return kwargs

        with torch.inference_mode():
            result = self.pipe(image=images or None, prompt_embeds=prompt_embeds, width=width, height=height,
                num_inference_steps=4, guidance_scale=1.0,
                generator=torch.Generator('cpu').manual_seed(settings['seed']),
                callback_on_step_end=progress).images[0]
        peak = round(torch.cuda.max_memory_allocated() / 1048576)
        # Hand cached blocks back so an idle warm worker holds only the model weights.
        gc.collect()
        torch.cuda.empty_cache()
        buffer = io.BytesIO()
        result.save(buffer, format='PNG')
        return {'image': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
            'width': result.width, 'height': result.height, 'seconds': round(time.perf_counter() - started, 2),
            'seed': settings['seed'], 'style': settings['style'], 'device': 'cuda',
            'model': 'FLUX.2 Klein 4B · Q5_K_M', 'engine': 'flux', 'postProcessing': None,
            'mode': settings['mode'], 'referenceCount': len(images), 'effectivePrompt': prompt, 'promptTokens': token_count,
            'peakMiB': peak, 'warmModel': warm,
            'settings': {key: settings[key] for key in ('seed', 'resolution', 'style', 'prompt', 'mode', 'aspect', 'controls', 'preserve')}}


def serve(lines, engine=None):
    """One JSON job per input line; every job ends with a done event. EOF ends the worker.

    A rejected request (ValueError) leaves the loaded model usable. Any other failure,
    out-of-memory included, ends the process so the driver returns all of its VRAM.
    """
    engine = engine or Engine()
    for line in lines:
        if not line.strip():
            continue
        fatal = False
        try:
            emit({'result': engine.generate(json.loads(line))})
        except ValueError as error:
            emit({'error': str(error)})
        except Exception:
            # Diagnostic traceback stays in the local log; HTTP receives a concise error.
            import traceback
            traceback.print_exc(file=sys.stderr)
            emit({'error': 'تعذر تشغيل FLUX محليًا. راجع سجل التشغيل؛ قد تكون الذاكرة غير كافية.'})
            fatal = True
        emit({'done': True})
        if fatal:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(serve(sys.stdin))
