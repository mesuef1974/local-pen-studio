import uuid

from accounts.models import User
from accounts.tests.test_api import Api
from audit.models import AuditEvent
from projects.models import Approval, ImageVersion, ImmutableError
from projects.tests.test_api import PNG, Base


class VersionTests(Base):
    def setUp(self):
        super().setUp()
        self.project = self.create(self.owner).json()['id']
        self.path = f'/projects/{self.project}/versions'
        self.sha = self.upload(self.owner).json()['sha256']

    def add(self, api=None, asset=None, source='upload', **body):
        return (api or self.owner).post(self.path, {'asset': asset or self.sha, 'source': source, **body})

    def approve(self, version_id, api=None, **options):
        return (api or self.owner).post(f'{self.path}/{version_id}/approve', **options)

    def test_create_is_idempotent_and_audited(self):
        first, again = self.add(), self.add()
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()['id'], again.json()['id'])
        child = self.add(source='prepare', parent_id=first.json()['id'])
        self.assertEqual((child.status_code, child.json()['parent_id']), (201, first.json()['id']))
        self.assertEqual([v['id'] for v in self.owner.get(self.path).json()],
                         [first.json()['id'], child.json()['id']])
        self.assertEqual(AuditEvent.objects.filter(action='version.created').count(), 2)

    def test_approval_belongs_to_one_version(self):
        first = self.add().json()['id']
        made, again = self.approve(first), self.approve(first)
        self.assertEqual((made.status_code, again.status_code), (201, 200))
        self.assertEqual((made.json()['id'], made.json()['approved_by']), (again.json()['id'], 'owner'))
        edited = self.upload(self.owner, PNG + b'-edited').json()['sha256']
        child = self.add(asset=edited, source='prepare', parent_id=first).json()
        self.assertEqual(child['approvals'], [])
        self.assertEqual(len(self.owner.get(f'{self.path}/{first}').json()['approvals']), 1)
        self.assertEqual(AuditEvent.objects.filter(action='version.approved').count(), 1)

    def test_another_account_gets_nothing(self):
        version = self.add().json()['id']
        User.objects.filter(username='other').update(role='supervisor')
        self.assertEqual(self.other.get(self.path).status_code, 404)
        self.assertEqual(self.other.get(f'{self.path}/{version}').status_code, 404)
        self.assertEqual(self.add(self.other).status_code, 404)
        self.assertEqual(self.approve(version, self.other).status_code, 404)
        self.assertEqual(Approval.objects.count(), 0)

    def test_asset_and_parent_must_belong_here(self):
        theirs = self.upload(self.other, PNG + b'-theirs').json()['sha256']
        self.assertEqual(self.add(asset=theirs).status_code, 404)
        self.assertEqual(self.add(parent_id=str(uuid.uuid4())).status_code, 404)
        elsewhere = self.create(self.owner).json()['id']
        foreign = self.owner.post(f'/projects/{elsewhere}/versions', {'asset': self.sha, 'source': 'upload'}).json()
        self.assertEqual(self.add(parent_id=foreign['id']).status_code, 404)
        self.assertEqual(self.approve(foreign['id']).status_code, 404)
        self.assertEqual(self.add(source='other').status_code, 422)

    def test_anonymous_csrf_temporary_password_and_deleted_project(self):
        version = self.add().json()['id']
        self.assertEqual(Api().get(self.path).status_code, 401)
        self.assertEqual(self.approve(version, csrf=False).status_code, 403)
        User.objects.filter(username='owner').update(must_change_password=True)
        self.assertEqual(self.approve(version).status_code, 403)
        User.objects.filter(username='owner').update(must_change_password=False)
        self.owner.post(f'/projects/{self.project}/delete')
        self.assertEqual(self.owner.get(self.path).status_code, 404)
        self.assertEqual(self.approve(version).status_code, 404)

    def test_rows_cannot_be_changed_or_deleted(self):
        self.approve(self.add().json()['id'])
        for model in (ImageVersion, Approval):
            row = model.objects.get()
            with self.assertRaises(ImmutableError):
                row.save()
            with self.assertRaises(ImmutableError):
                row.delete()
            with self.assertRaises(ImmutableError):
                model.objects.all().update(created_at=row.created_at)
            with self.assertRaises(ImmutableError):
                model.objects.all().delete()
