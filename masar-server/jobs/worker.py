"""Runs queued jobs in the FLUX service process, one at a time, in a process of its own.

The service validates the request itself. This side feeds it, keeps the job's heartbeat,
passes a cancel on, and stores what comes back.
"""
import base64
import binascii
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from django.conf import settings

from accounts.errors import DomainError
from jobs import services
from projects import storage
from projects.services import ASSET_REF

sys.path.append(str(settings.BASE_DIR.parent / 'flux-studio'))
import engine_pipe  # noqa: E402

LOG = logging.getLogger('masar.worker')
PNG_PREFIX = 'data:image/png;base64,'
JOB_TIMEOUT = 1200
CANCEL_GRACE = 20


def _message(job):
    """The stored inputs with each asset reference replaced by the image the service expects."""
    assets = {asset.sha256: asset for asset in job.assets.all()}

    def data_url(reference):
        asset = assets[ASSET_REF.fullmatch(reference)[1]]
        with storage.open_for_read(asset.sha256) as file:
            encoded = base64.b64encode(file.read()).decode()
        return f'data:{asset.content_type};base64,{encoded}'

    message = dict(job.inputs)
    if message.get('image'):
        message['image'] = data_url(message['image'])
    if message.get('references'):
        message['references'] = [item | {'image': data_url(item['image'])} for item in message['references']]
    return message | {'jobId': str(job.pk)}


def _png(result):
    image = result.get('image') if isinstance(result, dict) else None
    if isinstance(image, str) and image.startswith(PNG_PREFIX):
        try:
            data = base64.b64decode(image[len(PNG_PREFIX):], validate=True)
        except binascii.Error:
            data = b''
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return data
    return None


class Worker:
    def __init__(self, command=None, log_path=None, keep_warm=None, tick=2.0):
        self.command = command or [engine_pipe.PYTHON, engine_pipe.SERVICE]
        self.log_path = Path(log_path or settings.BASE_DIR / 'var' / 'worker-engine.log')
        self.keep_warm = engine_pipe.keep_warm_seconds() if keep_warm is None else keep_warm
        self.tick = tick
        self.cancel_file = Path(tempfile.gettempdir()) / f'masar-worker-cancel-{os.getpid()}.txt'
        self.process = self.log = None
        self.idle_since = 0.0

    def run_one(self):
        """Run the oldest queued job. False when there was nothing to take."""
        job = services.claim_next()
        if job is None:
            return False
        LOG.info('job %s: attempt %s', job.pk, job.attempts)
        try:
            result, failure = self._generate(job)
            image = _png(result)
            if image is None:
                error = failure or 'انتهت عملية التوليد قبل إخراج صورة. جرّب دقة أقل.'
                services.fail(job.pk, job.attempts, str(error))
            else:
                meta = {key: value for key, value in result.items() if key != 'image'}
                services.complete(job.pk, job.attempts, image, meta)
        except DomainError as error:
            # Only 'job_lost' arrives here: the job was taken back, so nothing is written to it.
            LOG.warning('job %s: %s', job.pk, error.code)
            self.discard()
        except Exception:
            LOG.exception('job %s failed', job.pk)
            self.discard()
            services.fail(job.pk, job.attempts, 'تعذر تشغيل مهمة التوليد المحلية.')
        self.idle_since = time.monotonic()
        return True

    def unload_if_idle(self):
        if self.process and time.monotonic() - self.idle_since >= self.keep_warm:
            self.discard()

    def discard(self):
        process, log = self.process, self.log
        self.process = self.log = None
        engine_pipe.stop(process, log)

    def _generate(self, job):
        message = _message(job)
        self.cancel_file.unlink(missing_ok=True)
        if not self.process or self.process.poll() is not None:
            self.discard()
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.process, self.log = engine_pipe.spawn(self.command, self.log_path, self.cancel_file)
        process = self.process
        engine_pipe.send(process, message, self.keep_warm)
        progress, reply = {}, []

        def on_event(event):
            progress.update({key: event[key] for key in ('step', 'total', 'phase') if key in event})

        # The pipe is read aside so the heartbeat goes on while the model loads in silence.
        reader = threading.Thread(target=lambda: reply.append(engine_pipe.read_reply(process, on_event)),
                                  daemon=True)
        reader.start()
        try:
            self._watch(job, process, reader, progress)
        except BaseException:
            engine_pipe.terminate_tree(process)  # ends the reader too
            reader.join(5)
            raise
        if not reply:
            raise RuntimeError('the service output could not be read')
        result, failure, done = reply[0]
        # A service that answered and is still alive keeps the model for the next job.
        if not (self.keep_warm and done and process.poll() is None):
            self.discard()
        return result, failure

    def _watch(self, job, process, reader, progress):
        deadline = time.monotonic() + JOB_TIMEOUT
        force_at = None
        while reader.is_alive():
            reader.join(self.tick)
            cancel = services.heartbeat(job.pk, job.attempts, **dict(progress))
            now = time.monotonic()
            if cancel and force_at is None:
                force_at = now + CANCEL_GRACE
                if self.keep_warm and progress.get('phase') in ('prompt', 'draw'):
                    # Past model loading the service stops at its next step and keeps the model.
                    self.cancel_file.write_text(str(job.pk), encoding='utf-8')
                else:
                    engine_pipe.terminate_tree(process)
            if reader.is_alive() and (now >= deadline or (force_at is not None and now >= force_at)):
                engine_pipe.terminate_tree(process)
