import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import generation


def image():
    buffer = io.BytesIO()
    Image.new('RGB', (80, 120), 'white').save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class FluxTests(unittest.TestCase):
    def test_presets_generate_instructions_without_style_filters(self):
        for style in generation.STYLES:
            data = generation.validate({'image': image(), 'style': style, 'prompt': 'Use a white background.'})
            prompt = generation.prompts(data)
            self.assertIn('white background', prompt)
            self.assertIn('Preserve facial identity only when a face is present there', prompt)
            self.assertIn('Retain only clothing or accessories visible in the main reference', prompt)
        source = Path('generation_service.py').read_text()
        self.assertNotIn('import cv2', source)
        self.assertNotIn('StableDiffusion', source)
        self.assertIn('num_inference_steps=4, guidance_scale=1.0', source)

    def test_reject_inactive_legacy_controls(self):
        for key, value in [('strength', .5), ('preserveSource', True), ('negativePrompt', 'text'), ('steps', 30)]:
            with self.assertRaises(ValueError):
                generation.validate({'image': image(), key: value})

    def test_input_boundaries(self):
        for extra in [{'seed': True}, {'seed': -1}, {'resolution': 769}, {'resolution': True},
                      {'style': 'other'}, {'prompt': 'x' * 1201}, {'style': 'custom'}, {'image': 'bad'}]:
            with self.assertRaises(ValueError):
                generation.validate({'image': image()} | extra)

    def test_text_only_does_not_condition_on_loaded_image_or_preservation(self):
        settings = generation.validate({'mode': 'generate', 'style': 'generate-lines', 'image': image()})
        self.assertIsNone(settings['image'])
        self.assertNotIn("subject's identity", generation.prompts(settings))
        self.assertEqual(generation.dimensions(settings | {'aspect': 'wide', 'resolution': 512}), (512, 288))

    def test_multi_reference_requires_roles_and_rejects_wrong_modes(self):
        settings = generation.validate({'image': image(), 'mode': 'multi', 'references': [{'image': image(), 'role': 'style'}]})
        self.assertIn('Reference image 2:', generation.prompts(settings))
        for bad in [{'mode': 'multi'}, {'references': [{'image': image(), 'role': 'style'}]},
                    {'mode': 'multi', 'references': [{'image': image(), 'role': 'unknown'}]},
                    {'mode': 'multi', 'references': [{'image': image(), 'role': 'style'}] * 3},
                    {'mode': 'generate', 'references': [{'image': image(), 'role': 'style'}]}]:
            with self.assertRaises(ValueError):generation.validate({'image': image()} | bad)

    def test_control_and_preservation_rules_actually_change_instruction(self):
        settings = generation.validate({'image': image(), 'controls': {'detail': 'low', 'shading': 'none'}, 'preserve': {'pose': False}})
        prompt = generation.prompts(settings)
        self.assertIn('omit small textures', prompt)
        self.assertIn('no tonal fills', prompt)
        self.assertNotIn("Keep the main reference's pose", prompt)
        self.assertIn('Preserve facial identity only when a face is present there', prompt)
        for bad in [{'controls': {'detail': 'fake'}}, {'controls': {'strength': 99}}, {'preserve': {'pose': 1}}, {'aspect': '../x'}]:
            with self.assertRaises(ValueError):generation.validate({'image': image()} | bad)

    def test_catalog_is_complete_and_presets_fit_editable_field(self):
        self.assertEqual(len(generation.PRESETS), 24)
        self.assertEqual(len(generation.STYLES), 24)
        for preset in generation.PRESETS.values():
            self.assertLessEqual(len(preset['prompt']), 1200)
            self.assertIn(preset['mode'], ('edit', 'multi', 'generate'))

    def test_output_dimensions_keep_ratios_without_cropping_references(self):
        settings = generation.validate({'image': image(), 'resolution': 512})
        self.assertEqual(generation.dimensions(settings, (480, 640)), (384, 512))
        self.assertEqual(generation.dimensions(settings | {'aspect': 'square'}, (480, 640)), (512, 512))
        self.assertEqual(generation.dimensions(settings | {'aspect': 'landscape'}), (512, 352))

    def test_prompt_budget_counts_token_ids_not_encoding_dictionary_keys(self):
        from generation_service import prompt_token_count
        class Tokenizer:
            def apply_chat_template(self, messages, tokenize, **kwargs):
                if tokenize:return {'input_ids': list(range(513)), 'attention_mask': [1] * 513}
                return 'formatted chat instruction'
            def __call__(self, text, **kwargs):
                return {'input_ids': list(range(513)), 'attention_mask': [1] * 513}
        self.assertEqual(prompt_token_count(Tokenizer(), 'instruction'), 513)

    def test_gate_released_if_worker_launch_fails(self):
        gate = threading.Lock()
        jobs = generation.Jobs(gate)
        with patch('generation.availability', return_value=(True, '')), patch('threading.Thread.start', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                jobs.start({'image': image()})
        self.assertFalse(gate.locked())
        self.assertEqual(jobs.job['state'], 'failed')

    def test_job_ids_keep_completed_result_when_another_page_starts_work(self):
        gate = threading.Lock()
        jobs = generation.Jobs(gate)
        with patch('generation.availability', return_value=(True, '')), patch('threading.Thread.start'):
            first = jobs.start({'image': image()})['job']
            jobs.job.update(state='complete', result={'image': image()})
            gate.release()
            second = jobs.start({'image': image()})['job']
            self.assertNotEqual(first, second)
            self.assertEqual(jobs.status(first)['job']['state'], 'complete')
            self.assertIn('result', jobs.status(first)['job'])
            self.assertNotIn('result', jobs.status(first, summary=True)['job'])
            self.assertTrue(jobs.status()['processing'])
            self.assertIsNone(jobs.status('unknown')['job'])
            gate.release()

    def test_busy_and_missing_model_are_reported_without_running(self):
        gate = threading.Lock()
        jobs = generation.Jobs(gate)
        with patch('generation.availability', return_value=(False, 'missing')):
            with self.assertRaisesRegex(ValueError, 'missing'):
                jobs.start({'image': image()})
        self.assertIsNone(jobs.job)
        gate.acquire()
        with patch('generation.availability', return_value=(True, '')):
            with self.assertRaises(BlockingIOError):
                jobs.start({'image': image()})
        gate.release()

    def test_manifest_file_sizes_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = {'model': generation.MODEL_ID, 'revision': generation.REVISION,
                        'files': {generation.QUANT_FILE: {'bytes': 4}}}
            (root / 'verified.json').write_text(json.dumps(manifest))
            with patch('generation.MODEL_DIR', root), patch('generation.PYTHON', Path(__file__)):
                self.assertFalse(generation.availability()[0])
                (root / generation.QUANT_FILE).write_bytes(b'1234')
                self.assertTrue(generation.availability()[0])

    def test_status_without_job_id_exposes_progress_only(self):
        gate = threading.Lock()
        jobs = generation.Jobs(gate)
        self.assertIsNone(jobs.status()['job'])
        with patch('generation.availability', return_value=(True, '')), patch('threading.Thread.start'):
            job_id = jobs.start({'image': image()})['job']
            jobs.job.update(state='complete', step=4, total=4, result={'image': image(), 'effectivePrompt': 'secret'})
            for summary in (False, True):
                self.assertEqual(jobs.status(summary=summary)['job'], {'state': 'complete', 'step': 4, 'total': 4})
            self.assertEqual(jobs.status(job_id)['job']['result']['effectivePrompt'], 'secret')
            gate.release()

    def test_only_png_jpeg_webp_content_is_decoded(self):
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'white').save(buffer, 'BMP')
        with self.assertRaises(ValueError):
            generation.image_bytes('data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode())
        self.assertTrue(generation.image_bytes(image()))

    def test_worker_noise_on_stdout_is_ignored_and_crashes_are_logged(self):
        class Worker:
            def __init__(self, lines):
                self.stdin = io.StringIO()
                self.stdout = io.StringIO(lines)
            def wait(self, timeout=None):
                return 0
            def poll(self):
                return 0
        result = {'image': image(), 'width': 80, 'height': 120}
        lines = 'library banner, not JSON\n[1, 2]\n' + json.dumps({'state': 'running', 'step': 2, 'total': 4}) + '\n' + json.dumps({'result': result}) + '\n'
        with tempfile.TemporaryDirectory() as folder, patch('generation.ROOT', Path(folder)), patch('generation.availability', return_value=(True, '')), patch('threading.Thread.start'):
            gate = threading.Lock()
            jobs = generation.Jobs(gate)
            job_id = jobs.start({'image': image()})['job']
            with patch('generation.subprocess.Popen', return_value=Worker(lines)):
                jobs._run({})
            self.assertEqual(jobs.status(job_id)['job']['state'], 'complete')
            self.assertFalse(gate.locked())
            job_id = jobs.start({'image': image()})['job']
            with patch('generation.subprocess.Popen', side_effect=RuntimeError('boom')), self.assertLogs('flux-studio', 'ERROR') as logs:
                jobs._run({})
            self.assertEqual(jobs.status(job_id)['job']['error'], 'تعذر تشغيل مهمة التوليد المحلية.')
            self.assertIn('boom', logs.output[0])
            self.assertFalse(gate.locked())

    def live_worker(self, events):
        """A worker that stays alive until its stdin closes, answering from a scripted event list."""
        class Pipe:
            def __init__(self):
                self.lines = []
                self.closed = False
            def write(self, text):
                self.lines.append(text)
            def flush(self):
                pass
            def close(self):
                self.closed = True
        class Output:
            def readline(self):
                return events.pop(0) if events else ''
            def close(self):
                pass
        class Worker:
            def __init__(self):
                self.stdin = Pipe()
                self.stdout = Output()
            def poll(self):
                return 0 if self.stdin.closed else None
            def wait(self, timeout=None):
                return 0
        return Worker()

    def test_warm_worker_serves_consecutive_jobs_and_unloads_when_idle(self):
        result = json.dumps({'result': {'image': image(), 'width': 80, 'height': 120}}) + '\n'
        done = json.dumps({'done': True}) + '\n'
        rejected = json.dumps({'error': 'طلب مرفوض'}) + '\n'
        worker = self.live_worker([result, done, rejected, done, result, done])
        with tempfile.TemporaryDirectory() as folder, patch('generation.ROOT', Path(folder)), patch('generation.availability', return_value=(True, '')), \
                patch('threading.Thread.start'), patch('generation.subprocess.Popen', return_value=worker) as popen:
            gate = threading.Lock()
            jobs = generation.Jobs(gate, keep_warm=60)
            states = []
            for _ in range(3):
                job_id = jobs.start({'image': image()})['job']
                jobs._run({'seed': 1})
                states.append(jobs.status(job_id)['job'])
                self.assertFalse(gate.locked())
                self.assertTrue(jobs.status()['modelLoaded'])
            self.assertEqual([job['state'] for job in states], ['complete', 'failed', 'complete'])
            self.assertEqual(states[1]['error'], 'طلب مرفوض')
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(len(worker.stdin.lines), 3)
            self.assertTrue(all(line.endswith('\n') for line in worker.stdin.lines))
            # A stale timer token must not unload, a busy gate must not unload, the current token does.
            jobs._unload_if_idle(jobs.idle_token - 1)
            self.assertTrue(jobs.status()['modelLoaded'])
            gate.acquire()
            jobs._unload_if_idle(jobs.idle_token)
            self.assertTrue(jobs.status()['modelLoaded'])
            gate.release()
            jobs._unload_if_idle(jobs.idle_token)
            self.assertFalse(jobs.status()['modelLoaded'])
            self.assertTrue(worker.stdin.closed)
            self.assertFalse(gate.locked())

    def test_worker_is_replaced_after_it_dies_and_not_kept_without_keep_warm(self):
        result = json.dumps({'result': {'image': image(), 'width': 80, 'height': 120}}) + '\n'
        done = json.dumps({'done': True}) + '\n'
        crashed = self.live_worker([json.dumps({'error': 'نفدت الذاكرة'}) + '\n', done])
        crashed.poll = lambda: 1  # the worker exits after a fatal error
        fresh = self.live_worker([result, done])
        with tempfile.TemporaryDirectory() as folder, patch('generation.ROOT', Path(folder)), patch('generation.availability', return_value=(True, '')), \
                patch('threading.Thread.start'), patch('generation.subprocess.Popen', side_effect=[crashed, fresh]) as popen:
            gate = threading.Lock()
            jobs = generation.Jobs(gate, keep_warm=60)
            first = jobs.start({'image': image()})['job']
            jobs._run({})
            self.assertEqual(jobs.status(first)['job']['error'], 'نفدت الذاكرة')
            self.assertFalse(jobs.status()['modelLoaded'])
            second = jobs.start({'image': image()})['job']
            jobs._run({})
            self.assertEqual(jobs.status(second)['job']['state'], 'complete')
            self.assertEqual(popen.call_count, 2)
            gate.acquire()
            jobs.unload()
            gate.release()
            self.assertFalse(jobs.status()['modelLoaded'])
            cold = self.live_worker([result, done])
            popen.side_effect = [cold]
            jobs.keep_warm = 0
            third = jobs.start({'image': image()})['job']
            jobs._run({})
            self.assertEqual(jobs.status(third)['job']['state'], 'complete')
            self.assertTrue(cold.stdin.closed)
            self.assertFalse(jobs.status()['modelLoaded'])

    def test_worker_loop_survives_rejected_requests_and_stops_on_fatal_errors(self):
        import generation_service

        class Engine:
            def generate(self, data):
                if data.get('bad'):
                    raise ValueError('طلب مرفوض')
                if data.get('crash'):
                    raise RuntimeError('CUDA out of memory')
                return {'seed': data['seed']}
        events = []
        lines = ['\n', json.dumps({'seed': 1}) + '\n', json.dumps({'bad': True}) + '\n', 'not json\n',
                 json.dumps({'seed': 2}) + '\n', json.dumps({'crash': True}) + '\n', json.dumps({'seed': 3}) + '\n']
        with patch('generation_service.emit', side_effect=events.append), patch('sys.stderr', io.StringIO()):
            self.assertEqual(generation_service.serve(lines, Engine()), 1)
        self.assertEqual([event['result']['seed'] for event in events if 'result' in event], [1, 2])
        self.assertEqual(sum(1 for event in events if event.get('done')), 5)
        self.assertEqual(events[2], {'error': 'طلب مرفوض'})
        self.assertNotIn('CUDA', json.dumps(events))
        with patch('generation_service.emit', side_effect=events.append):
            self.assertEqual(generation_service.serve([], Engine()), 0)

    def test_keep_warm_setting_is_bounded(self):
        for raw, expected in (('0', 0.0), ('45', 45.0), ('-1', 300.0), ('99999', 300.0), ('abc', 300.0), ('nan', 300.0)):
            with patch.dict('os.environ', {'FLUX_KEEP_WARM_S': raw}):
                self.assertEqual(generation.keep_warm_seconds(), expected)


if __name__ == '__main__':
    unittest.main()
