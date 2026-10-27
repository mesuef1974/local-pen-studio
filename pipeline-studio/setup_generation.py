"""Explicit one-time download of official SDXL FP16 files. Never used by image APIs."""
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / 'models' / 'sdxl-base-1.0'
MODEL_ID = 'stabilityai/stable-diffusion-xl-base-1.0'
REVISION = '462165984030d82259a11f4367a4eed129e94a7b'
FILES = ['model_index.json', 'scheduler/scheduler_config.json',
         'text_encoder/config.json', 'text_encoder/model.fp16.safetensors',
         'text_encoder_2/config.json', 'text_encoder_2/model.fp16.safetensors',
         'unet/config.json', 'unet/diffusion_pytorch_model.fp16.safetensors',
         'vae/config.json', 'vae/diffusion_pytorch_model.fp16.safetensors']
FILES += [f'{folder}/{name}' for folder in ['tokenizer', 'tokenizer_2']
          for name in ['merges.txt', 'vocab.json', 'special_tokens_map.json', 'tokenizer_config.json']]


def download_large(name, size):
    """Bounded resumable ranges avoid a stalled multi-GB HTTP response."""
    import requests
    target = MODEL_DIR / name
    if target.is_file() and target.stat().st_size == size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.partial')
    journal = target.with_suffix(target.suffix + '.chunks.json')
    chunk_size = 32 * 1024 * 1024
    count = (size + chunk_size - 1) // chunk_size
    try:
        saved = json.loads(journal.read_text()) if partial.exists() and journal.exists() else []
        if not isinstance(saved, list) or any(type(i) is not int or not 0 <= i < count for i in saved):
            raise ValueError()
        done = set(saved)
    except (OSError, ValueError, TypeError):
        done = set()
    if not partial.exists():
        with partial.open('wb') as output:
            output.truncate(size)
    lock = threading.Lock()

    def chunk(index):
        start = index * chunk_size
        end = min(size - 1, start + chunk_size - 1)
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
        for attempt in range(4):
            try:
                with requests.get(url, headers={'Range': f'bytes={start}-{end}'}, timeout=(20, 60)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}' or len(response.content) != end - start + 1:
                        raise RuntimeError('Unexpected download range')
                    with partial.open('r+b') as output:
                        output.seek(start); output.write(response.content)
                with lock:
                    done.add(index)
                    temporary = journal.with_suffix('.tmp')
                    temporary.write_text(json.dumps(sorted(done)))
                    temporary.replace(journal)
                    if len(done) % 8 == 0 or len(done) == count:
                        print(f'UNet downloaded: {len(done)}/{count} chunks', flush=True)
                return
            except Exception:
                if attempt == 3:
                    raise
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(chunk, [index for index in range(count) if index not in done]))
    partial.replace(target)
    return target


def install():
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True)
    entries = {entry.rfilename: entry for entry in info.siblings}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {'model': MODEL_ID, 'revision': REVISION, 'files': {}}
    total = sum(entries[name].size for name in FILES)
    print(f'Official SDXL FP16: {total / 1e9:.2f} GB; {len(FILES)} files', flush=True)
    for name in FILES + ['LICENSE.md', 'README.md']:
        entry = entries[name]
        path = (download_large(name, entry.size) if entry.size > 3_000_000_000 else
                Path(hf_hub_download(MODEL_ID, name, revision=REVISION, local_dir=MODEL_DIR)))
        if path.stat().st_size != entry.size:
            raise RuntimeError(f'Incomplete file: {name}')
        checksum = hashlib.sha256(path.read_bytes()).hexdigest() if not entry.lfs else None
        if entry.lfs:
            hasher = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    hasher.update(chunk)
            checksum = hasher.hexdigest()
            if checksum != entry.lfs.sha256:
                # Preserve failed bytes for diagnosis, but never reuse them on retry.
                from time import time_ns
                path.replace(path.with_suffix(path.suffix + f'.corrupt-{time_ns()}'))
                raise RuntimeError(f'Checksum mismatch, file quarantined; rerun setup: {name}')
        if name in FILES:
            manifest['files'][name] = {'bytes': entry.size, 'sha256': checksum}
        print(f'Verified {name}', flush=True)
    (MODEL_DIR / 'verified.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('SDXL ready for offline generation.', flush=True)


if __name__ == '__main__':
    install()
