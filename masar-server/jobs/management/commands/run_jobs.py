import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from jobs.worker import Worker

POLL_SECONDS = 2


class Command(BaseCommand):
    help = 'Run queued generation jobs with the local FLUX service.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='run at most one job, then exit')

    def handle(self, *args, once=False, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
        worker = Worker()
        self.stdout.write('Job worker running. Ctrl+C stops it.')
        try:
            while True:
                close_old_connections()
                busy = worker.run_one()
                if once:
                    break
                if not busy:
                    worker.unload_if_idle()
                    time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            pass  # a job cut short here is retried once its heartbeat goes silent
        finally:
            worker.discard()
