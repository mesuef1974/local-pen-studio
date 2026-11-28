from urllib.parse import urlencode

from django.contrib.staticfiles import finders
from django.test import TestCase

from accounts import services
from accounts.models import Role
from audit.models import AuditEvent
from projects import services as projects

PASSWORD = 'a-long-test-passphrase'


class AdminTests(TestCase):
    def setUp(self):
        make = lambda name, role: services.create_user(actor=None, username=name, full_name=name, role=role,
                                                       password=PASSWORD)[0]
        self.boss, self.teacher = make('boss', Role.SUPERVISOR), make('teacher', Role.TEACHER)
        projects.create_project(owner=self.boss, title='mine-title')
        projects.create_project(owner=self.teacher, title='theirs-title')

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

    def test_read_only_and_own_projects_only(self):
        self.sign_in('boss')
        page = self.client.get('/admin/projects/project/')
        self.assertContains(page, 'mine-title')
        self.assertNotContains(page, 'theirs-title')
        for model in ('accounts/user', 'projects/project', 'projects/asset', 'audit/auditevent'):
            self.assertEqual(self.client.get(f'/admin/{model}/').status_code, 200, model)
            self.assertEqual(self.client.get(f'/admin/{model}/add/').status_code, 403, model)
        detail = self.client.get(f'/admin/accounts/user/{self.teacher.pk}/change/')
        self.assertNotContains(detail, 'argon2')

    def test_only_the_admin_may_load_its_own_files(self):
        self.assertIn("default-src 'self'", self.client.get('/admin/login/')['Content-Security-Policy'])
        self.assertIn("default-src 'none'", self.client.get('/api/auth/csrf')['Content-Security-Policy'])
        self.assertTrue(finders.find('admin/css/base.css'))
        self.assertEqual(self.client.get('/static/admin/css/base.css').status_code, 200)
