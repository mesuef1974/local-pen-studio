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
            def wait(self):
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


if __name__ == '__main__':
    unittest.main()
