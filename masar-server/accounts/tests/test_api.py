from datetime import timedelta
from io import StringIO
from unittest import mock, skipUnless

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts import services
from accounts.models import LoginThrottle, Role, User
from audit.models import AppendOnlyError, AuditEvent

PASSWORD = 'Test-only-passphrase-41'
NEW_PASSWORD = 'Another-test-passphrase-92'


def make_user(username, role=Role.TEACHER):
    user, _ = services.create_user(actor=None, username=username, full_name='اسم تجريبي',
                                   role=role, password=PASSWORD)
    return user


class Api:
    """A browser-like client: keeps cookies and sends the CSRF token it was given."""

    def __init__(self):
        self.client = Client(enforce_csrf_checks=True)

    def token(self):
        self.client.get('/api/auth/csrf', secure=True)
        return self.client.cookies['csrftoken'].value

    def post(self, path, body=None, csrf=True, **extra):
        if csrf:
            extra['HTTP_X_CSRFTOKEN'] = self.token()
            extra['HTTP_REFERER'] = 'https://testserver/'
        return self.client.post(f'/api{path}', body or {}, content_type='application/json',
                                secure=True, **extra)

    def get(self, path):
        return self.client.get(f'/api{path}', secure=True)

    def login(self, username, password=PASSWORD):
        return self.post('/auth/login', {'username': username, 'password': password})


def signed_in(username):
    api = Api()
    assert api.login(username).status_code == 200
    return api


class SignInTests(TestCase):
    def setUp(self):
        self.user = make_user('teacher1')

    def test_sign_in_me_and_sign_out(self):
        api = Api()
        response = api.login('  TEACHER1 ')
        self.assertEqual(response.status_code, 200)
        cookie = response.cookies['masar_session']
        self.assertTrue(cookie['httponly'])
        self.assertTrue(cookie['secure'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(api.get('/auth/me').json()['username'], 'teacher1')
        self.assertEqual(api.post('/auth/logout').status_code, 204)
        self.assertEqual(api.get('/auth/me').status_code, 401)

    def test_password_is_stored_with_argon2(self):
        self.assertTrue(self.user.password.startswith('argon2$'))

    def test_wrong_password_unknown_and_disabled_look_the_same(self):
        disabled = make_user('teacher2')
        User.objects.filter(pk=disabled.pk).update(is_active=False)
        answers = [Api().login('teacher1', 'wrong-password-123'), Api().login('nobody'),
                   Api().login('teacher2')]
        self.assertEqual({(r.status_code, r.content) for r in answers}, {(401, answers[0].content)})

    def test_login_requires_csrf_token(self):
        response = Api().post('/auth/login', {'username': 'teacher1', 'password': PASSWORD}, csrf=False)
        self.assertEqual(response.status_code, 403)

    def test_session_actions_require_csrf_token(self):
        api = signed_in('teacher1')
        self.assertEqual(api.post('/auth/logout', csrf=False).status_code, 403)
        self.assertEqual(api.get('/auth/me').status_code, 200)

    def test_account_is_throttled_even_with_the_right_password(self):
        for _ in range(5):
            self.assertEqual(Api().login('teacher1', 'wrong-password-123').status_code, 401)
        self.assertEqual(Api().login('teacher1').status_code, 429)
        LoginThrottle.objects.update(window_started_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(Api().login('teacher1').status_code, 200)

    @override_settings(LOGIN_FAILURE_LIMIT_PER_ADDRESS=3)
    def test_address_is_throttled_across_account_names(self):
        for name in ('a1x', 'b2x', 'c3x'):
            self.assertEqual(Api().login(name).status_code, 401)
        self.assertEqual(Api().login('teacher1').status_code, 429)

    @override_settings(LOGIN_FAILURE_LIMIT_PER_ADDRESS=3)
    def test_successful_sign_ins_do_not_use_up_the_address_limit(self):
        for _ in range(6):
            self.assertEqual(Api().login('teacher1').status_code, 200)

    def test_session_ends_after_absolute_age(self):
        api = signed_in('teacher1')
        later = timezone.now() + timedelta(hours=13)
        with mock.patch('accounts.middleware.timezone.now', return_value=later):
            self.assertEqual(api.get('/auth/me').status_code, 401)

    def test_disabling_an_account_ends_its_session(self):
        api = signed_in('teacher1')
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(api.get('/auth/me').status_code, 401)

    def test_enabling_again_does_not_revive_an_old_session(self):
        boss = make_user('boss', Role.SUPERVISOR)
        api = signed_in('teacher1')
        services.set_active(actor=boss, user_id=self.user.pk, active=False)
        services.set_active(actor=boss, user_id=self.user.pk, active=True)
        self.assertEqual(api.get('/auth/me').status_code, 401)

    def test_rejected_attempts_are_logged_once_per_window(self):
        for _ in range(20):
            Api().login('teacher1', 'wrong-password-123')
        self.assertEqual(AuditEvent.objects.filter(action='auth.throttled').count(), 1)

    def test_unknown_names_are_not_logged_and_nul_is_refused_cleanly(self):
        self.assertEqual(Api().login('typed-a-secret-here').status_code, 401)
        self.assertEqual(Api().login('a\x00b').status_code, 401)
        self.assertNotIn('typed-a-secret', str(list(AuditEvent.objects.values())))

    def test_unknown_host_is_refused(self):
        response = Client().get('/api/auth/csrf', HTTP_HOST='evil.example')
        self.assertEqual(response.status_code, 400)

    def test_responses_are_not_cached_and_docs_are_off(self):
        response = Api().get('/auth/csrf')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(Api().get('/docs').status_code, 404)
        self.assertEqual(Api().get('/openapi.json').status_code, 404)


class PasswordTests(TestCase):
    def setUp(self):
        make_user('teacher1')

    def change(self, api, current, new):
        return api.post('/auth/change-password', {'current_password': current, 'new_password': new})

    def test_change_keeps_this_session_and_ends_the_others(self):
        first, second = signed_in('teacher1'), signed_in('teacher1')
        self.assertEqual(self.change(first, PASSWORD, NEW_PASSWORD).status_code, 204)
        self.assertEqual(first.get('/auth/me').status_code, 200)
        self.assertEqual(second.get('/auth/me').status_code, 401)
        self.assertEqual(Api().login('teacher1').status_code, 401)

    def test_weak_same_and_wrong_current_are_refused(self):
        api = signed_in('teacher1')
        self.assertEqual(self.change(api, PASSWORD, 'short').json()['code'], 'weak_password')
        self.assertEqual(self.change(api, PASSWORD, PASSWORD).json()['code'], 'same_password')
        self.assertEqual(self.change(api, 'not-the-password', NEW_PASSWORD).json()['code'], 'wrong_password')

    def test_reset_during_a_change_wins(self):
        boss = make_user('boss', Role.SUPERVISOR)
        api = signed_in('teacher1')
        original, fresh = services._check_password_rules, []

        def reset_midway(password, user):
            original(password, user)
            fresh.append(services.reset_password(actor=boss, user_id=user.pk)[1])

        with mock.patch('accounts.services._check_password_rules', reset_midway):
            self.assertEqual(self.change(api, PASSWORD, NEW_PASSWORD).status_code, 401)
        self.assertEqual(Api().login('teacher1', fresh[0]).status_code, 200)

    def test_guessing_the_current_password_is_throttled(self):
        api = signed_in('teacher1')
        for _ in range(5):
            self.change(api, 'not-the-password', NEW_PASSWORD)
        self.assertEqual(self.change(api, PASSWORD, NEW_PASSWORD).status_code, 429)


class AdministrationTests(TestCase):
    def setUp(self):
        self.boss = make_user('boss', Role.SUPERVISOR)
        self.teacher = make_user('teacher1')
        self.api = signed_in('boss')

    def new_teacher(self):
        response = self.api.post('/users', {'username': 'teacher9', 'full_name': 'معلم تاسع'})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_new_account_must_change_its_temporary_password(self):
        created = self.api.post('/users', {'username': 'boss2', 'full_name': 'مشرف ثان',
                                           'role': 'supervisor'}).json()
        api = Api()
        self.assertEqual(api.login('boss2', created['temporary_password']).status_code, 200)
        self.assertEqual(api.get('/users').json()['code'], 'password_change_required')
        api.post('/auth/change-password', {'current_password': created['temporary_password'],
                                           'new_password': NEW_PASSWORD})
        self.assertEqual(api.get('/users').status_code, 200)

    def test_duplicate_and_invalid_accounts_are_refused(self):
        self.new_teacher()
        again = self.api.post('/users', {'username': 'TEACHER9', 'full_name': 'مكرر'})
        self.assertEqual(again.status_code, 409)
        bad = self.api.post('/users', {'username': 'a b', 'full_name': 'اسم'})
        self.assertEqual(bad.json()['code'], 'invalid_username')
        role = self.api.post('/users', {'username': 'teacher8', 'full_name': 'اسم', 'role': 'root'})
        self.assertEqual(role.json()['code'], 'invalid_role')

    def test_teacher_cannot_use_any_supervisor_action(self):
        api = signed_in('teacher1')
        target = self.boss.pk
        answers = [api.get('/users'), api.get('/audit'),
                   api.post('/users', {'username': 'intruder', 'full_name': 'دخيل'}),
                   api.post(f'/users/{target}/disable'), api.post(f'/users/{target}/enable'),
                   api.post(f'/users/{target}/reset-password')]
        self.assertEqual([r.status_code for r in answers], [403] * len(answers))

    def test_anonymous_gets_401_everywhere(self):
        api = Api()
        answers = [api.get('/users'), api.get('/audit'), api.get('/auth/me'),
                   api.post(f'/users/{self.boss.pk}/disable')]
        self.assertEqual([r.status_code for r in answers], [401] * len(answers))

    def test_disable_is_idempotent_and_audited_once(self):
        for _ in range(2):
            self.assertEqual(self.api.post(f'/users/{self.teacher.pk}/disable').status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(action='user.disabled').count(), 1)
        self.assertEqual(Api().login('teacher1').status_code, 401)
        self.api.post(f'/users/{self.teacher.pk}/enable')
        self.assertEqual(Api().login('teacher1').status_code, 200)

    def test_supervisor_cannot_disable_or_reset_themself(self):
        self.assertEqual(self.api.post(f'/users/{self.boss.pk}/disable').status_code, 409)
        self.assertEqual(self.api.post(f'/users/{self.boss.pk}/reset-password').status_code, 409)

    def test_reset_password_ends_sessions_and_unlocks(self):
        teacher_api = signed_in('teacher1')
        for _ in range(5):
            Api().login('teacher1', 'wrong-password-123')
        fresh = self.api.post(f'/users/{self.teacher.pk}/reset-password').json()
        self.assertEqual(teacher_api.get('/auth/me').status_code, 401)
        self.assertEqual(Api().login('teacher1', fresh['temporary_password']).status_code, 200)

    def test_audit_never_holds_passwords(self):
        created = self.new_teacher()
        Api().login('teacher9', 'wrong-password-123')
        text = str(list(AuditEvent.objects.values()))
        for secret in (PASSWORD, created['temporary_password'], 'wrong-password-123'):
            self.assertNotIn(secret, text)
        events = self.api.get('/audit?limit=200').json()
        self.assertTrue({'auth.login', 'auth.failed', 'user.created'} <= {e['action'] for e in events})

    def test_audit_events_cannot_be_changed_through_the_orm(self):
        event = AuditEvent.objects.first()
        for change in (event.save, event.delete, AuditEvent.objects.all().delete,
                       lambda: AuditEvent.objects.update(action='x')):
            with self.assertRaises(AppendOnlyError):
                change()

    @skipUnless(connection.vendor == 'postgresql', 'the trigger exists only in PostgreSQL')
    def test_database_itself_refuses_to_delete_audit_rows(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM audit_auditevent')
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('TRUNCATE audit_auditevent')


class CommandTests(TestCase):
    def test_create_supervisor_reads_the_password_from_a_hidden_prompt(self):
        with mock.patch('accounts.management.commands.create_supervisor.getpass', return_value=PASSWORD):
            call_command('create_supervisor', 'owner', 'المالك', stdout=StringIO())
        user = User.objects.get(username='owner')
        self.assertEqual((user.role, user.must_change_password), (Role.SUPERVISOR, False))
        self.assertTrue(user.check_password(PASSWORD))
