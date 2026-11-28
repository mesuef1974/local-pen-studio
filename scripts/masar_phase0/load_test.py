"""Masar phase 0: back-to-back FLUX jobs on one warm worker, as a multi-user queue would run them.

Talks to generation_service.py directly, so the studio server and its browser storage are not touched.
Run with the system Python while no other work uses the card:
    python scripts/masar_phase0/load_test.py --out result.json
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[2] / 'flux-studio'
PYTHON = STUDIO / '.venv-flux' / 'Scripts' / 'python.exe'


def gpu():
    values = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,temperature.gpu,clocks.sm,power.draw',
                                      '--format=csv,noheader,nounits'], text=True).split(',')
    return dict(zip(('usedMiB', 'tempC', 'clockMHz', 'watts'), (float(v) for v in values)))


def batches(image, count):
    reference = {'image': image, 'role': 'style'}
    # A different prompt per job, so the text encoder runs each time as it would for different teachers.
    for name, number, extra in [('edit-768', count, {'mode': 'edit', 'resolution': 768}),
                                ('edit-1024', count, {'mode': 'edit', 'resolution': 1024}),
                                ('multi3-1024', 3, {'mode': 'multi', 'resolution': 1024,
                                                    'references': [reference, reference]})]:
        for index in range(number):
            yield name, {'image': image, 'seed': 100 + index, 'style': 'ink',
                         'prompt': f'variation {name} {index}'} | extra


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--count', type=int, default=10)
    args = parser.parse_args()
    image = 'data:image/png;base64,' + base64.b64encode((STUDIO / 'sample-ink.png').read_bytes()).decode()
    runs = []
    log_path = Path(tempfile.gettempdir()) / 'masar-phase0-worker.log'
    with log_path.open('w', encoding='utf-8') as log:
        worker = subprocess.Popen([str(PYTHON), str(STUDIO / 'generation_service.py')], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8')
        try:
            for number, (batch, job) in enumerate(batches(image, args.count)):
                started = time.perf_counter()
                worker.stdin.write(json.dumps(job | {'jobId': str(number)}) + '\n')
                worker.stdin.flush()
                record = {'batch': batch}
                for line in iter(worker.stdout.readline, ''):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if 'result' in event:
                        record |= {key: event['result'][key] for key in ('width', 'height', 'peakMiB', 'warmModel')}
                    if 'error' in event:
                        record['error'] = event['error']
                    if event.get('done'):
                        break
                else:
                    record['error'] = 'worker ended'
                record |= {'wallSeconds': round(time.perf_counter() - started, 2)} | gpu()
                runs.append(record)
                args.out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')
                print(json.dumps(record, ensure_ascii=True), flush=True)
                if 'error' in record:
                    return 1
        finally:
            worker.stdin.close()
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main())
