"""Explicit, resumable download. Image processing never downloads or uploads images."""
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / 'models/flux2-klein-4b'
MODEL_ID = 'black-forest-labs/FLUX.2-klein-4B'
REVISION = 'e7b7dc27f91deacad38e78976d1f2b499d76a294'
QUANT_ID = 'unsloth/FLUX.2-klein-4B-GGUF'
QUANT_REVISION = '0084d1df98e2e2137fe776d55170bc4792ec1d66'
QUANT_FILE = 'flux-2-klein-4b-Q5_K_M.gguf'


def verify(target, size, expected):
    """Return the file's SHA-256. A bad file is set aside so that the next run downloads it again."""
    hasher = hashlib.sha256()
    with target.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            hasher.update(block)
    if target.stat().st_size != size or (expected and hasher.hexdigest() != expected):
        quarantined = target.with_name(f'{target.name}.corrupt-{time.time_ns()}')
        target.replace(quarantined)
        raise RuntimeError(f'Integrity check failed; kept as {quarantined.name}. Rerun setup to download it again.')
    return hasher.hexdigest()


def install():
    import requests
    # Reuse the project's bounded, journaled downloader; no old model is modified.
    import importlib.util
    spec = importlib.util.spec_from_file_location('range_download', ROOT.parent / 'pipeline-studio/setup_generation.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.MODEL_DIR = MODEL_DIR
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {'model': MODEL_ID, 'revision': REVISION, 'quantization': 'Q5_K_M', 'files': {}}
    progress = ROOT / 'setup-progress.json'
    sources = []
    for repo, revision in [(MODEL_ID, REVISION), (QUANT_ID, QUANT_REVISION)]:
        response = requests.get(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true', timeout=30)
        response.raise_for_status()
        for entry in response.json()['siblings']:
            name = entry['rfilename']
            if ((repo == MODEL_ID and (name == 'model_index.json' or name == 'transformer/config.json'
                    or name.startswith(('text_encoder/', 'tokenizer/', 'vae/', 'scheduler/'))))
                    or (repo == QUANT_ID and name == QUANT_FILE)):
                sources.append((repo, revision, name, entry))
    total = sum(entry['size'] for _, _, _, entry in sources)
    completed = 0
    print(f'FLUX Q5_K_M and components: {total / 1e9:.2f} GB', flush=True)
    for repo, revision, name, entry in sources:
        progress.write_text(json.dumps({'state': 'downloading', 'file': name, 'verifiedBytes': completed, 'totalBytes': total}))
        helper.MODEL_ID, helper.REVISION = repo, revision
        target = MODEL_DIR / name
        if entry['size'] > 32 * 1024 * 1024:
            helper.download_large(name, entry['size'])
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(f'https://huggingface.co/{repo}/resolve/{revision}/{name}', timeout=(20, 120))
            response.raise_for_status()
            temporary = target.with_suffix(target.suffix + '.partial')
            temporary.write_bytes(response.content)
            temporary.replace(target)
        digest = verify(target, entry['size'], entry.get('lfs', {}).get('sha256'))
        manifest['files'][name] = {'bytes': entry['size'], 'sha256': digest, 'repo': repo, 'revision': revision}
        completed += entry['size']
        print(f'Verified {name}', flush=True)
    (MODEL_DIR / 'verified.json').write_text(json.dumps(manifest, indent=2))
    progress.write_text(json.dumps({'state': 'complete', 'verifiedBytes': completed, 'totalBytes': total}))
    print('FLUX ready for offline inference.', flush=True)


if __name__ == '__main__':
    try:
        install()
    except Exception:
        (ROOT / 'setup-progress.json').write_text(json.dumps({'state': 'failed'}))
        raise
