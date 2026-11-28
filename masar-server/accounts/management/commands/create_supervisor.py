from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from accounts import services
from accounts.errors import DomainError
from accounts.models import Role


class Command(BaseCommand):
    help = 'Create a supervisor account. The password is typed at a hidden prompt.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('full_name')

    def handle(self, *args, username, full_name, **options):
        password = getpass('Password: ')
        if password != getpass('Repeat password: '):
            raise CommandError('The two passwords differ.')
        try:
            user, _ = services.create_user(actor=None, username=username, full_name=full_name,
                                           role=Role.SUPERVISOR, password=password)
        except DomainError as error:
            raise CommandError(error.message) from error
        self.stdout.write(f'Created supervisor {user.username}.')
