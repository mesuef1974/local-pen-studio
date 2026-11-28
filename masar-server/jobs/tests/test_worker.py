"""The worker against a real child process that speaks the FLUX service protocol, without a GPU."""
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command

from jobs import services
from jobs.models import Job
from jobs.tests.test_jobs import JobBase
from jobs.worker import Worker
from projects import storage
from projects.tests.test_api import PNG

FAKE_SERVICE = r'''
import base64, json, os, sys, time
def emit(event):
    print(json.dumps(event), flush=True)
RESULT = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'test-only-image-result').decode()
for line in sys.stdin:
    data = json.loads(line)
    prompt = data.get('prompt', '')
    print('a library banner')
    emit({'state': 'running', 'step': 1, 'total': 4, 'phase': 'draw'})
    if prompt == 'crash':
        sys.exit(1)
    if prompt == 'reject':
        emit({'error': 'the engine refused'})
    elif prompt == 'wait':
        for _ in range(200):
            if os.path.exists(os.environ['FLUX_CANCEL_FILE']):
                break
            time.sleep(0.05)
        emit({'cancelled': True})
    else:
        emit({'result': {'image': RESULT, 'seed': data.get('seed'), 'pid': os.getpid(),
                         'got': [data.get('image', '')[:22]] + [r['image'][:22] for r in data.get('references', [])]}})
    emit({'done': True})
'''


class RunnerTests(JobBase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        script = Path(folder.name) / 'service.py'
        script.write_text(FAKE_SERVICE, encoding='utf-8')
        self.worker = Worker(command=[sys.executable, script], log_path=Path(folder.name) / 'engine.log',
                             keep_warm=60, tick=0.05)
        self.addCleanup(self.worker.discard)  # runs before the folder is removed

    def queue(self, prompt='ok', **inputs):
        return self.job(inputs={'mode': 'generate', 'prompt': prompt, 'seed': 7, **inputs})['id']

    def run_job(self, job_id):
        self.assertTrue(self.worker.run_one())
        return Job.objects.get(pk=job_id)

    def test_a_result_is_stored_and_the_service_stays_loaded(self):
        first = self.run_job(self.queue())
        self.assertEqual((first.status, first.step, first.total, first.phase), ('succeeded', 1, 4, 'draw'))
        self.assertEqual(first.result_meta['seed'], 7)
        self.assertNotIn('image', first.result_meta)
        with storage.open_for_read(first.result.sha256) as file:
            self.assertEqual(file.read(), PNG + b'-result')
        second = self.run_job(self.queue())
        self.assertEqual(second.result_meta['pid'], first.result_meta['pid'])
        self.assertFalse(self.worker.run_one())

    def test_asset_references_reach_the_service_as_images(self):
        main, extra = self.asset(), self.asset(data=b'\xff\xd8\xff-second')
        job_id = self.job(inputs={'mode': 'multi', 'image': main,
                                  'references': [{'image': extra, 'role': 'style'}]})['id']
        job = self.run_job(job_id)
        self.assertEqual(job.result_meta['got'], ['data:image/png;base64,', 'data:image/jpeg;base64'])
        self.assertEqual(job.inputs['image'], main)  # the stored request keeps references

    def test_a_refusal_and_a_crash_fail_the_job_and_the_next_one_still_runs(self):
        refused = self.run_job(self.queue('reject'))
        self.assertEqual((refused.status, refused.error), ('failed', 'the engine refused'))
        crashed = self.run_job(self.queue('crash'))
        self.assertEqual(crashed.status, 'failed')
        self.assertTrue(crashed.error)
        self.assertEqual(self.run_job(self.queue()).status, 'succeeded')

    def test_a_missing_input_file_fails_the_job_without_a_retry(self):
        job_id = self.job(inputs={'mode': 'edit', 'image': self.asset()})['id']
        with mock.patch('projects.storage.open_for_read', side_effect=FileNotFoundError), \
                self.assertLogs('masar.worker', 'ERROR'):
            job = self.run_job(job_id)
        self.assertEqual((job.status, job.attempts), ('failed', 1))

    def test_cancel_reaches_a_running_service_and_keeps_it_loaded(self):
        job_id = self.queue('wait')
        beat = services.heartbeat

        def cancel_while_drawing(pk, attempt, **progress):
            if progress.get('phase') == 'draw':
                services.cancel_job(owner=Job.objects.get(pk=pk).owner, job_id=pk)
            return beat(pk, attempt, **progress)

        with mock.patch('jobs.services.heartbeat', side_effect=cancel_while_drawing):
            job = self.run_job(job_id)
        self.assertEqual((job.status, job.result), ('cancelled', None))
        self.assertIsNotNone(self.worker.process)
        self.assertIsNone(self.worker.process.poll())

    def test_a_job_taken_back_is_left_alone(self):
        job_id = self.queue('wait')

        def taken_back(pk, attempt, **progress):
            Job.objects.filter(pk=pk).update(attempts=attempt + 1)
            return beat(pk, attempt, **progress)

        beat = services.heartbeat
        with mock.patch('jobs.services.heartbeat', side_effect=taken_back), self.assertLogs('masar.worker'):
            job = self.run_job(job_id)
        self.assertEqual((job.status, job.attempts), ('running', 2))
        self.assertIsNone(self.worker.process)

    def test_an_idle_service_is_unloaded(self):
        self.run_job(self.queue())
        self.worker.unload_if_idle()
        self.assertIsNotNone(self.worker.process)
        self.worker.keep_warm = 0
        self.worker.unload_if_idle()
        self.assertIsNone(self.worker.process)

    def test_queued_jobs_of_a_deleted_project_are_cancelled(self):
        project_id = self.create(self.owner).json()['id']
        job_id = self.job(project_id=project_id)['id']
        self.owner.post(f'/projects/{project_id}/delete')
        self.assertFalse(self.worker.run_one())
        job = Job.objects.get(pk=job_id)
        self.assertEqual(job.status, 'cancelled')
        self.assertIsNotNone(job.finished_at)

    def test_the_command_runs_one_job_and_exits(self):
        job_id = self.queue()
        with mock.patch('jobs.management.commands.run_jobs.Worker', return_value=self.worker), \
                mock.patch('jobs.management.commands.run_jobs.close_old_connections'):
            call_command('run_jobs', once=True, stdout=StringIO())
        self.assertEqual(Job.objects.get(pk=job_id).status, 'succeeded')
        self.assertIsNone(self.worker.process)
