"""The Django admin, read-only. Changes stay in the services, which keep the rules and the audit log."""
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect

from accounts import services
from accounts.errors import DomainError
from accounts.models import Role, User
from audit.models import AuditEvent
from jobs.models import Job
from projects.models import Asset, Project


class SignInForm(AdminAuthenticationForm):
    """Sign in through the service: same attempt limit, audit event and session lifetime as the API."""

    def clean(self):
        username, password = self.cleaned_data.get('username'), self.cleaned_data.get('password')
        if username and password:
            try:
                self.user_cache = services.sign_in(self.request, username, password)
            except DomainError as error:
                raise ValidationError(error.message) from error
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class MasarAdminSite(admin.AdminSite):
    site_header = site_title = 'إدارة مسار'
    site_url = None
    login_form = SignInForm

    def has_permission(self, request):
        user = request.user
        return (user.is_authenticated and user.is_active and user.role == Role.SUPERVISOR
                and not user.must_change_password)

    def logout(self, request, extra_context=None):
        if request.method == 'POST' and request.user.is_authenticated:
            services.sign_out(request)
        return super().logout(request, extra_context)

    def password_change(self, request, extra_context=None):
        # The studio page owns password changes; the admin one would skip the rules and the audit log.
        return HttpResponseRedirect(f'http://{request.get_host().split(":")[0]}:8770/projects')


class ReadOnly(admin.ModelAdmin):
    actions = None

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OwnOnly(ReadOnly):
    """A supervisor does not see other people's work."""

    def get_queryset(self, request):
        return super().get_queryset(request).filter(owner=request.user)


class UserAdmin(ReadOnly):
    fields = list_display = ('username', 'full_name', 'role', 'is_active', 'must_change_password', 'created_at')
    search_fields = ('username', 'full_name')


class ProjectAdmin(OwnOnly):
    fields = list_display = ('title', 'revision', 'created_at', 'updated_at', 'deleted_at')


class AssetAdmin(OwnOnly):
    fields = list_display = ('sha256', 'content_type', 'size', 'created_at')


class JobAdmin(OwnOnly):
    fields = ('inputs', 'status', 'review', 'attempts', 'error', 'result_meta', 'created_at', 'started_at',
              'finished_at')
    list_display = ('prompt', 'status', 'review', 'created_at', 'finished_at')
    list_filter = ('status', 'review')

    @admin.display(description='الوصف')
    def prompt(self, job):
        return str(job.inputs.get('prompt') or job.inputs.get('style') or job.kind)[:60]


class AuditAdmin(ReadOnly):
    fields = list_display = ('created_at', 'actor_username', 'action', 'target_type', 'target_id', 'ip_address',
                             'detail')
    list_filter = ('action',)


site = MasarAdminSite()
site.register(User, UserAdmin)
site.register(Project, ProjectAdmin)
site.register(Asset, AssetAdmin)
site.register(Job, JobAdmin)
site.register(AuditEvent, AuditAdmin)
