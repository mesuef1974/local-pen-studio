import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class Role(models.TextChoices):
    TEACHER = 'teacher', 'معلم'
    SUPERVISOR = 'supervisor', 'مشرف'


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TEACHER)
    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BaseUserManager()

    USERNAME_FIELD = 'username'

    class Meta:
        ordering = ['username']
        constraints = [
            models.CheckConstraint(condition=models.Q(role__in=Role.values), name='user_role_valid'),
        ]

    # What the read-only Django admin asks of a user; there are no per-object permission tables.
    @property
    def is_staff(self):
        return self.is_active and self.role == Role.SUPERVISOR

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name


class LoginThrottle(models.Model):
    """Failed or in-flight sign-in attempts for one account name or one address."""

    key = models.CharField(max_length=80, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField()
