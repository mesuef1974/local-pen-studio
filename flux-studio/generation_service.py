"""Raw local FLUX image editing. No style filters or SDXL fallback."""
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


def emit(event):
    print(json.dumps(event, ensure_ascii=True), flush=True)


def prompt_token_count(tokenizer, prompt):
    # Transformers versions may return a BatchEncoding for tokenize=True.
    # Count the token IDs themselves, including the same chat template as inference.
    text = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False)
    return len(tokenizer(text, truncation=False)['input_ids'])


def run(data):
    from generation import validate, prompts, dimensions, image_bytes
    from setup_flux import MODEL_DIR, QUANT_FILE
    from PIL import Image, ImageOps
    import torch
    from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel, GGUFQuantizationConfig
    settings = validate(data)
    if not torch.cuda.is_available():
        raise ValueError('تشغيل FLUX يحتاج إتاحة كرت NVIDIA على الجهاز.')
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    emit({'state': 'loading', 'step': 0, 'total': 0})
    from transformers import Qwen2TokenizerFast
    tokenizer = Qwen2TokenizerFast.from_pretrained(str(MODEL_DIR / 'tokenizer'), local_files_only=True)
    prompt = prompts(settings)
    token_count = prompt_token_count(tokenizer, prompt)
    if token_count > 512:
        raise ValueError('الوصف والتوجيهات تتجاوز 512 رمزًا. اختصر الوصف أو قلّل التوجيهات؛ لم يُقص النص تلقائيًا.')
    transformer = Flux2Transformer2DModel.from_single_file(
        str(MODEL_DIR / QUANT_FILE), config=str(MODEL_DIR), subfolder='transformer',
        quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
        dtype=torch.bfloat16, local_files_only=True)
    pipe = Flux2KleinPipeline.from_pretrained(str(MODEL_DIR), transformer=transformer, tokenizer=tokenizer,
        dtype=torch.bfloat16, local_files_only=True)
    # Accelerate's recursive meta hooks discard GGUF quantization metadata.
    # Offload only the unquantized text encoder, then free it before image inference.
    from accelerate import cpu_offload
    import gc
    cpu_offload(pipe.text_encoder, execution_device=torch.device('cuda'))
    with torch.inference_mode():
        prompt_embeds, _ = pipe.encode_prompt(prompt, device=torch.device('cuda'))
    pipe.text_encoder = None
    gc.collect()
    torch.cuda.empty_cache()
    pipe.to('cuda')
    pipe.vae.enable_tiling()
    pipe.set_progress_bar_config(disable=True)
    images = []
    if settings['mode'] != 'generate':
        for encoded in [settings['image']] + [ref['image'] for ref in settings['references']]:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes(encoded)))).convert('RGBA')
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
        result = pipe(image=images or None, prompt_embeds=prompt_embeds, width=width, height=height,
            num_inference_steps=4, guidance_scale=1.0,
            generator=torch.Generator('cpu').manual_seed(settings['seed']),
            callback_on_step_end=progress).images[0]
    buffer = io.BytesIO()
    result.save(buffer, format='PNG')
    emit({'result': {'image': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
        'width': result.width, 'height': result.height, 'seconds': round(time.perf_counter() - started, 2),
        'seed': settings['seed'], 'style': settings['style'], 'device': 'cuda',
        'model': 'FLUX.2 Klein 4B · Q5_K_M', 'engine': 'flux', 'postProcessing': None,
        'mode': settings['mode'], 'referenceCount': len(images), 'effectivePrompt': prompt, 'promptTokens': token_count,
        'peakMiB': round(torch.cuda.max_memory_allocated() / 1048576),
        'settings': {key: settings[key] for key in ('seed', 'resolution', 'style', 'prompt', 'mode', 'aspect', 'controls', 'preserve')}}})


if __name__ == '__main__':
    try:
        run(json.load(sys.stdin))
    except Exception as error:
        # Diagnostic traceback stays in the local log; HTTP receives a concise error.
        import traceback
        traceback.print_exc(file=sys.stderr)
        emit({'error': str(error) if isinstance(error, ValueError) else
            'تعذر تشغيل FLUX محليًا. راجع سجل التشغيل؛ قد تكون الذاكرة غير كافية.'})
        sys.exit(1)
