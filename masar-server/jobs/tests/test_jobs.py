import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.errors import DomainError
from accounts.models import User
from accounts.tests.test_api import Api
from audit.models import AuditEvent
from jobs import services
from jobs.models import Job
from projects.tests.test_api import PNG, Base

RESULT = PNG + b'-result'


class JobBase(Base):
    def submit(self, api, inputs=None, key=None, **body):
        return api.post('/jobs', {'inputs': inputs or {'mode': 'generate', 'prompt': 'قط', 'seed': 7},
                                  'idempotency_key': key or str(uuid.uuid4()), **body})

    def job(self, api=None, **body):
        response = self.submit(api or self.owner, **body)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def asset(self, api=None, data=PNG):
        return 'asset:' + self.upload(api or self.owner, data).json()['sha256']


class ApiTests(JobBase):
    def test_create_is_idempotent_and_audited(self):
        key = str(uuid.uuid4())
        first, again = self.submit(self.owner, key=key), self.submit(self.owner, key=key)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual((first.json()['status'], first.json()['review']), ('queued', 'pending'))
        changed = self.submit(self.owner, {'mode': 'generate', 'prompt': 'كلب'}, key=key)
        self.assertEqual((changed.status_code, changed.json()['code']), (409, 'key_reused'))
        self.assertEqual(self.submit(self.other, key=key).status_code, 201)
        self.assertEqual(AuditEvent.objects.filter(action='job.created').count(), 2)

    def test_queue_limit_is_per_account_and_does_not_block_a_resend(self):
        key = str(uuid.uuid4())
        self.job(key=key)
        self.job()
        self.job()
        refused = self.submit(self.owner)
        self.assertEqual((refused.status_code, refused.json()['code']), (429, 'queue_full'))
        self.assertEqual(self.submit(self.owner, key=key).status_code, 200)
        self.job(self.other)

    def test_images_are_owned_asset_references(self):
        main, extra = self.asset(), self.asset(data=PNG + b'2')
        made = self.job(inputs={'mode': 'multi', 'image': main, 'references': [{'image': extra, 'role': 'style'}]})
        self.assertEqual(Job.objects.get(pk=made['id']).assets.count(), 2)
        theirs = self.asset(self.other, PNG + b'3')
        for inputs, code in (
            ({'mode': 'edit', 'image': theirs}, 'unknown_asset'),
            ({'mode': 'edit', 'image': 'data:image/png;base64,AAAA'}, 'inline_image'),
            ({'mode': 'edit', 'image': 'C:/secret.png'}, 'invalid_inputs'),
            ({'mode': 'edit'}, 'invalid_inputs'),
            ({'mode': 'generate', 'image': main}, 'invalid_inputs'),
            ({'mode': 'generate', 'jobId': 'x'}, 'invalid_inputs'),
            ({'mode': 'generate', 'prompt': 'a\x00'}, 'invalid_inputs'),
            ({'mode': 'multi', 'image': main, 'references': [{'image': main}]}, 'invalid_inputs'),
            ({'mode': 'multi', 'image': main, 'references': 'x'}, 'invalid_inputs'),
        ):
            response = self.submit(self.owner, inputs)
            self.assertEqual((response.status_code, response.json()['code']), (400, code), inputs)

    def test_project_must_be_the_owners(self):
        mine = self.create(self.owner).json()['id']
        theirs = self.create(self.other).json()['id']
        made = self.job(project_id=mine)
        self.job()
        self.assertEqual(self.submit(self.owner, project_id=theirs).status_code, 404)
        listed = self.owner.get(f'/jobs?project={mine}').json()
        self.assertEqual([row['id'] for row in listed], [made['id']])
        self.assertEqual(len(self.owner.get('/jobs').json()), 2)
        self.assertEqual(self.owner.get(f'/jobs?project={theirs}').status_code, 404)

    def test_another_account_cannot_see_or_change_a_job(self):
        path = f"/jobs/{self.job()['id']}"
        User.objects.filter(username='other').update(role='supervisor')
        self.assertEqual(self.other.get(path).status_code, 404)
        self.assertEqual(self.other.post(f'{path}/cancel').status_code, 404)
        self.assertEqual(self.other.post(f'{path}/review', {'review': 'accepted'}).status_code, 404)
        self.assertEqual(self.other.get('/jobs').json(), [])

    def test_anonymous_csrf_and_temporary_password(self):
        self.assertEqual(Api().get('/jobs').status_code, 401)
        self.assertEqual(self.owner.post('/jobs', {}, csrf=False).status_code, 403)
        path = f"/jobs/{self.job()['id']}"
        self.assertEqual(self.owner.post(f'{path}/cancel', csrf=False).status_code, 403)
        User.objects.filter(username='owner').update(must_change_password=True)
        self.assertEqual(self.owner.get('/jobs').status_code, 403)
        self.assertEqual(self.submit(self.owner).status_code, 403)

    def test_cancel_a_queued_job_once(self):
        path = f"/jobs/{self.job()['id']}"
        for _ in range(2):
            self.assertEqual(self.owner.post(f'{path}/cancel').json()['status'], 'cancelled')
        self.assertEqual(AuditEvent.objects.filter(action='job.cancelled').count(), 1)
        self.assertIsNone(services.claim_next())

    def test_review_needs_a_result(self):
        path = f"/jobs/{self.job()['id']}"
        early = self.owner.post(f'{path}/review', {'review': 'accepted'})
        self.assertEqual((early.status_code, early.json()['code']), (409, 'no_result'))
        job = services.claim_next()
        services.complete(job.pk, job.attempts, RESULT, {'seed': 7})
        self.assertEqual(self.owner.post(f'{path}/review', {'review': 'revise'}).json()['review'], 'revise')
        self.assertEqual(self.owner.post(f'{path}/review', {'review': 'great'}).status_code, 422)


class WorkerTests(JobBase):
    def claim(self):
        job = services.claim_next()
        self.assertIsNotNone(job)
        return job

    def stall(self, job):
        old = timezone.now() - timedelta(seconds=settings.JOB_HEARTBEAT_TIMEOUT + 1)
        Job.objects.filter(pk=job.pk).update(heartbeat_at=old)

    def test_one_job_runs_at_a_time_oldest_first(self):
        first = self.job()
        self.job(self.other)
        job = self.claim()
        self.assertEqual((str(job.pk), job.status, job.attempts), (first['id'], 'running', 1))
        self.assertIsNone(services.claim_next())

    def test_progress_result_and_history(self):
        path = f"/jobs/{self.job()['id']}"
        job = self.claim()
        self.assertFalse(services.heartbeat(job.pk, 1, step=2, total=4, phase='draw'))
        self.assertEqual(self.owner.get(path).json()['step'], 2)
        self.assertTrue(services.complete(job.pk, 1, RESULT, {'seed': 7, 'seconds': 3.5}))
        done = self.owner.get(path).json()
        self.assertEqual((done['status'], done['result'], done['result_meta']['seed']),
                         ('succeeded', hashlib.sha256(RESULT).hexdigest(), 7))
        download = self.owner.get(f"/assets/{done['result']}")
        # Read to the end: Windows cannot delete the temporary folder while the file is open.
        self.assertEqual(b''.join(download.streaming_content), RESULT)
        self.assertEqual(self.owner.post(f'{path}/cancel').json()['status'], 'succeeded')

    def test_cancel_a_running_job_discards_the_result(self):
        path = f"/jobs/{self.job()['id']}"
        job = self.claim()
        response = self.owner.post(f'{path}/cancel').json()
        self.assertEqual((response['status'], response['cancel_requested']), ('running', True))
        self.assertTrue(services.heartbeat(job.pk, 1))
        services.complete(job.pk, 1, RESULT, {})
        done = self.owner.get(path).json()
        self.assertEqual((done['status'], done['result']), ('cancelled', None))

    def test_failure_is_recorded(self):
        self.job()
        job = self.claim()
        services.fail(job.pk, 1, 'نفدت الذاكرة')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), ('failed', 'نفدت الذاكرة'))
        self.assertIsNotNone(job.finished_at)

    def test_a_silent_job_is_retried_once_then_fails(self):
        self.job()
        job = self.claim()
        self.stall(job)
        again = self.claim()
        self.assertEqual((again.pk, again.attempts), (job.pk, 2))
        # The first worker lost the job: it can no longer touch it.
        with self.assertRaises(DomainError):
            services.heartbeat(job.pk, 1)
        self.assertFalse(services.complete(job.pk, 1, RESULT, {}))
        self.stall(again)
        self.assertIsNone(services.claim_next())
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_a_silent_cancelled_job_is_not_retried(self):
        self.job()
        job = self.claim()
        services.cancel_job(owner=job.owner, job_id=job.pk)
        self.stall(job)
        self.assertIsNone(services.claim_next())
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
