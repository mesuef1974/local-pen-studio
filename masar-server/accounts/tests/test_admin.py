import uuid
from urllib.parse import urlencode

from django.contrib.staticfiles import finders
from django.test import Client, TestCase

from accounts import services
from accounts.models import Role, User
from audit.models import AuditEvent
from jobs import services as jobs
from projects import services as projects

PASSWORD = 'a-long-test-passphrase'


class AdminTests(TestCase):
    def setUp(self):
        make = lambda name, role: services.create_user(actor=None, username=name, full_name=name, role=role,
                                                       password=PASSWORD)[0]
        self.boss, self.teacher = make('boss', Role.SUPERVISOR), make('teacher', Role.TEACHER)
        projects.create_project(owner=self.boss, title='mine-title')
        projects.create_project(owner=self.teacher, title='theirs-title')
        for owner, word in ((self.boss, 'mine-prompt'), (self.teacher, 'theirs-prompt')):
            jobs.create_job(owner=owner, inputs={'mode': 'generate', 'prompt': word}, key=uuid.uuid4())

    def sign_in(self, username, password=PASSWORD):
        # Urlencoded, as the browser sends the form; multipart is refused by the server.
        return self.client.post('/admin/login/?next=/admin/', urlencode({'username': username, 'password': password}),
                                content_type='application/x-www-form-urlencoded')

    def test_supervisor_signs_in_through_the_service_and_stays_signed_in(self):
        self.assertRedirects(self.sign_in('boss'), '/admin/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action='auth.login', actor_username='boss').exists())
        self.client.post('/admin/logout/', content_type='application/x-www-form-urlencoded')
        self.assertTrue(AuditEvent.objects.filter(action='auth.logout', actor_username='boss').exists())
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_teacher_and_wrong_password_stay_out(self):
        self.assertEqual(self.sign_in('teacher').status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.sign_in('boss', 'wrong-password-here')
        self.assertTrue(AuditEvent.objects.filter(action='auth.failed').exists())

    def test_work_is_read_only_and_own_only(self):
        self.sign_in('boss')
        page = self.client.get('/admin/projects/project/')
        self.assertContains(page, 'mine-title')
        self.assertNotContains(page, 'theirs-title')
        for model in ('accounts/user', 'projects/project', 'projects/asset', 'jobs/job',
                      'audit/auditevent'):
            self.assertEqual(self.client.get(f'/admin/{model}/').status_code, 200, model)
            expected = 200 if model == 'accounts/user' else 403  # accounts alone are managed here
            self.assertEqual(self.client.get(f'/admin/{model}/add/').status_code, expected, model)
        page = self.client.get('/admin/jobs/job/')
        self.assertContains(page, 'mine-prompt')
        self.assertNotContains(page, 'theirs-prompt')
        detail = self.client.get(f'/admin/accounts/user/{self.teacher.pk}/change/')
        self.assertNotContains(detail, 'argon2')

    def post(self, url, data=None):
        return self.client.post(url, urlencode(data or {}), content_type='application/x-www-form-urlencoded')

    def test_supervisor_creates_an_account_and_sees_its_password_once(self):
        self.sign_in('boss')
        data = {'username': 'newbie', 'full_name': 'معلم جديد', 'role': 'teacher'}
        response = self.post('/admin/accounts/user/add/', data)
        password = response.context['password']
        self.assertContains(response, password)
        self.assertIn('no-store', response['Cache-Control'])
        user = User.objects.get(username='newbie')
        self.assertTrue(user.must_change_password and user.check_password(password))
        self.assertTrue(AuditEvent.objects.filter(action='user.created', actor_username='boss',
                                                  target_id=str(user.pk)).exists())
        self.assertNotContains(self.client.get('/admin/accounts/user/add/'), password)
        self.assertContains(self.post('/admin/accounts/user/add/', data), 'errornote')  # name taken

    def test_disable_enable_and_reset_ask_first_and_are_audited(self):
        self.sign_in('boss')
        url = f'/admin/accounts/user/{self.teacher.pk}/do/'
        for action, active in (('disable', False), ('enable', True)):
            self.assertContains(self.client.get(f'/admin/accounts/user/{self.teacher.pk}/change/'), url + action)
            self.assertEqual(self.client.get(url + action + '/').status_code, 200)
            self.teacher.refresh_from_db()
            self.assertNotEqual(self.teacher.is_active, active)  # a GET changes nothing
            self.assertEqual(self.post(url + action + '/').status_code, 302)
            self.teacher.refresh_from_db()
            self.assertEqual(self.teacher.is_active, active)
        password = self.post(url + 'reset-password/').context['password']
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.must_change_password and self.teacher.check_password(password))
        for action in ('user.disabled', 'user.enabled', 'user.password_reset'):
            self.assertTrue(AuditEvent.objects.filter(action=action, actor_username='boss').exists(), action)

    def test_management_is_refused_to_self_teachers_visitors_and_forged_requests(self):
        url = f'/admin/accounts/user/{self.teacher.pk}/do/disable/'
        self.assertEqual(self.post(url).status_code, 302)  # a visitor is sent to sign in
        self.sign_in('teacher')
        self.assertEqual(self.post(url).status_code, 302)
        self.sign_in('boss')
        mine = f'/admin/accounts/user/{self.boss.pk}/do/'
        self.assertContains(self.post(mine + 'disable/'), 'errornote')
        self.assertContains(self.post(mine + 'reset-password/'), 'errornote')
        self.assertNotContains(self.client.get(f'/admin/accounts/user/{self.boss.pk}/change/'), mine)
        forged = Client(enforce_csrf_checks=True)
        forged.cookies = self.client.cookies
        self.assertEqual(forged.post(url, '', content_type='application/x-www-form-urlencoded').status_code, 403)
        self.teacher.refresh_from_db()
        self.boss.refresh_from_db()
        self.assertTrue(self.teacher.is_active and self.boss.is_active)

    def test_only_the_admin_may_load_its_own_files(self):
        self.assertIn("default-src 'self'", self.client.get('/admin/login/')['Content-Security-Policy'])
        self.assertIn("default-src 'none'", self.client.get('/api/auth/csrf')['Content-Security-Policy'])
        self.assertTrue(finders.find('admin/css/base.css'))
        self.assertEqual(self.client.get('/static/admin/css/base.css').status_code, 200)
