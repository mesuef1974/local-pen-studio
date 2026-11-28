import json
import tempfile
import uuid
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from accounts.tests.test_api import Api, make_user, signed_in
from audit.models import AuditEvent
from projects.models import Asset, Project

PNG = b'\x89PNG\r\n\x1a\n' + b'test-only-image'


class Base(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(FILES_DIR=folder.name)
        settings.enable()
        self.addCleanup(settings.disable)
        make_user('owner')
        make_user('other')
        self.owner, self.other = signed_in('owner'), signed_in('other')

    def create(self, api, **body):
        return api.post('/projects', {'title': 'مشروع', **body})

    def upload(self, api, data=PNG, csrf=True):
        extra = {}
        if csrf:
            extra = {'HTTP_X_CSRFTOKEN': api.token(), 'HTTP_REFERER': 'https://testserver/'}
        return api.client.post('/api/assets', data, content_type='application/octet-stream', secure=True, **extra)

    def save(self, api, project_id, state, revision=0):
        return api.post(f'/projects/{project_id}/state', json.dumps({'revision': revision, 'state': state}))


class ProjectTests(Base):
    def test_create_is_idempotent_per_client_key(self):
        key = str(uuid.uuid4())
        first, again = self.create(self.owner, client_key=key), self.create(self.owner, client_key=key)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(self.create(self.other, client_key=key).status_code, 201)
        self.assertEqual(AuditEvent.objects.filter(action='project.created').count(), 2)

    def test_another_account_cannot_see_or_change_a_project(self):
        project_id = self.create(self.owner).json()['id']
        path = f'/projects/{project_id}'
        self.assertEqual(self.other.get(path).status_code, 404)
        self.assertEqual(self.other.post(f'{path}/rename', {'title': 'x'}).status_code, 404)
        self.assertEqual(self.save(self.other, project_id, {'a': 1}).status_code, 404)
        self.assertEqual(self.other.post(f'{path}/delete').status_code, 404)
        self.assertEqual(self.other.get('/projects').json(), [])

    def test_supervisor_role_gives_no_access_to_others(self):
        project_id = self.create(self.owner).json()['id']
        User.objects.filter(username='other').update(role='supervisor')
        self.assertEqual(self.other.get(f'/projects/{project_id}').status_code, 404)

    def test_anonymous_and_missing_csrf_are_refused(self):
        self.assertEqual(Api().get('/projects').status_code, 401)
        self.assertEqual(self.owner.post('/projects', {'title': 'x'}, csrf=False).status_code, 403)
        self.assertEqual(self.upload(self.owner, csrf=False).status_code, 403)
        project_id = self.create(self.owner).json()['id']
        body = json.dumps({'revision': 0, 'state': {}})
        self.assertEqual(self.owner.post(f'/projects/{project_id}/state', body, csrf=False).status_code, 403)

    def test_temporary_password_blocks_projects_and_assets(self):
        User.objects.filter(username='owner').update(must_change_password=True)
        self.assertEqual(self.owner.get('/projects').status_code, 403)
        self.assertEqual(self.upload(self.owner).status_code, 403)

    def test_state_revisions(self):
        project_id = self.create(self.owner).json()['id']
        self.assertEqual(self.save(self.owner, project_id, {'a': 1}).json()['revision'], 1)
        self.assertEqual(self.save(self.owner, project_id, {'a': 1}).json()['revision'], 1)  # resend
        self.assertEqual(self.save(self.owner, project_id, {'a': 2}).status_code, 409)
        self.assertEqual(self.save(self.owner, project_id, {'a': 2}, 1).json()['revision'], 2)
        self.assertEqual(self.owner.get(f'/projects/{project_id}').json()['state'], {'a': 2})

    @override_settings(MAX_STATE_BYTES=200_000)
    def test_state_may_exceed_the_global_body_limit_but_not_its_own(self):
        project_id = self.create(self.owner).json()['id']
        self.assertEqual(self.save(self.owner, project_id, {'a': 'x' * 100_000}).status_code, 200)
        self.assertEqual(self.save(self.owner, project_id, {'a': 'x' * 300_000}, 1).status_code, 413)

    def test_invalid_states_are_refused(self):
        project_id = self.create(self.owner).json()['id']
        bad = ['not json', '[]', '{"state":{}}', '{"revision":true,"state":{}}', '{"revision":0,"state":[]}',
               '{"revision":0,"state":{"a":NaN}}', '{"revision":0,"state":{"a":1e999}}',
               '{"revision":0,"state":{"a":"\\u0000"}}', '{"revision":0,"state":{"a":"\\ud800"}}',
               '{"revision":0,"state":{"a":"data:image/png;base64,AA"}}',
               '{"revision":0,"state":{"a":' + '[' * 100_000 + ']' * 100_000 + '}}']
        for body in bad:
            with self.subTest(body=body[:60]):
                self.assertEqual(self.owner.post(f'/projects/{project_id}/state', body).status_code, 400)
        # A literal backslash followed by u0000 is ordinary text.
        self.assertEqual(self.save(self.owner, project_id, {'a': '\\u0000'}).status_code, 200)

    def test_a_change_between_equal_python_values_is_saved(self):
        project_id = self.create(self.owner).json()['id']
        self.save(self.owner, project_id, {'v': 1, 'f': 0})
        self.assertEqual(self.save(self.owner, project_id, {'v': True, 'f': False}, 1).json()['revision'], 2)

    def test_multipart_is_refused_before_anything_is_read(self):
        with mock.patch('django.core.files.uploadhandler.TemporaryFileUploadHandler.receive_data_chunk') as chunk,                 mock.patch('django.core.files.uploadhandler.MemoryFileUploadHandler.receive_data_chunk') as small:
            response = Api().client.post('/api/assets', {'file': SimpleUploadedFile('a', b'x' * 100)}, secure=True)
        self.assertEqual(response.status_code, 415)
        self.assertFalse(chunk.called or small.called)

    def test_delete_hides_the_project_and_keeps_the_row(self):
        key = str(uuid.uuid4())
        project_id = self.create(self.owner, client_key=key).json()['id']
        self.assertEqual(self.owner.post(f'/projects/{project_id}/delete').status_code, 204)
        self.assertEqual(self.owner.get(f'/projects/{project_id}').status_code, 404)
        self.assertEqual(self.owner.get('/projects').json(), [])
        self.assertEqual(self.create(self.owner, client_key=key).status_code, 409)
        self.assertEqual(Project.objects.count(), 1)


class AssetTests(Base):
    def test_upload_is_deduplicated_and_downloaded_as_attachment(self):
        first, again = self.upload(self.owner), self.upload(self.owner)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), again.json())
        self.assertEqual(Asset.objects.count(), 1)
        response = self.owner.get(f"/assets/{first.json()['sha256']}")
        self.assertEqual(b''.join(response.streaming_content), PNG)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_assets_are_private_to_their_owner(self):
        sha256 = self.upload(self.owner).json()['sha256']
        self.assertEqual(self.other.get(f'/assets/{sha256}').status_code, 404)
        project_id = self.create(self.other).json()['id']
        response = self.save(self.other, project_id, {'source': f'asset:{sha256}'})
        self.assertEqual((response.status_code, response.json()['code']), (400, 'unknown_asset'))

    def test_state_links_the_assets_it_references(self):
        sha256 = self.upload(self.owner).json()['sha256']
        project_id = self.create(self.owner).json()['id']
        self.assertEqual(self.save(self.owner, project_id, {'source': f'asset:{sha256}'}).status_code, 200)
        self.assertEqual(Project.objects.get(pk=project_id).assets.count(), 1)

    @override_settings(MAX_ASSET_BYTES=100_000)
    def test_only_images_within_the_limit(self):
        self.assertEqual(self.upload(self.owner, b'<svg onload=alert(1)>').status_code, 415)
        self.assertEqual(self.upload(self.owner, PNG + b'x' * 100_000).status_code, 413)
        self.assertEqual(self.upload(self.owner, PNG + b'x' * 70_000).status_code, 200)
        self.assertEqual(self.owner.get('/assets/..%2F..%2F.env').status_code, 404)
        self.assertEqual(self.owner.get('/assets/%00').status_code, 404)
