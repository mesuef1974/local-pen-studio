"""HTTP handler contract: local-only access, bounded bodies, private job results, logged failures."""
import http.client
import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flux_server_http_test', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class HandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None, host=None, origin='same', content_type='application/json'):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Host': host or f'127.0.0.1:{self.port}'}
        if origin:
            headers['Origin'] = f'http://127.0.0.1:{self.port}' if origin == 'same' else origin
        if body is not None:
            headers['Content-Type'] = content_type
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read() or b'null')
        finally:
            connection.close()

    def test_foreign_host_and_origin_are_refused(self):
        self.assertEqual(self.request('GET', '/api/status', host='evil.example:80')[0], 403)
        for origin in (None, 'null', 'http://evil.example'):
            self.assertEqual(self.request('POST', '/api/editor', body='{}', origin=origin)[0], 403)
        status, headers, _ = self.request('GET', '/api/status')
        self.assertEqual(status, 200)
        self.assertNotIn('Python', headers['Server'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_bad_bodies_get_400_without_processing(self):
        with patch.object(server, 'process', side_effect=AssertionError('must not run')):
            self.assertEqual(self.request('POST', '/api/editor', body='{}', content_type='text/plain')[0], 400)
            self.assertEqual(self.request('POST', '/api/editor', body='[1]')[0], 400)
            self.assertEqual(self.request('POST', '/api/editor', body='{"a":' * 100_000)[0], 400)
            self.assertEqual(self.request('POST', '/api/editor', body='[' * 200_000)[0], 400)
        self.assertEqual(self.request('POST', '/server.py', body='{}')[0], 404)
        self.assertEqual(self.request('GET', '/server.py')[0], 404)

    def test_unexpected_failure_is_logged_and_hidden_from_the_client(self):
        with patch.object(server, 'process', side_effect=RuntimeError('C:/private/path detail')), self.assertLogs('flux-studio', 'ERROR') as logs:
            status, _, body = self.request('POST', '/api/editor', body='{}')
        self.assertEqual(status, 500)
        self.assertNotIn('private', body['error'])
        self.assertIn('private/path detail', logs.output[0])
        self.assertIn('/api/editor', logs.output[0])
        self.assertFalse(server.GATE.locked())

    def test_generation_status_without_job_id_has_no_result_or_id(self):
        job = {'id': 'a' * 32, 'state': 'complete', 'step': 4, 'total': 4, 'result': {'image': 'data', 'effectivePrompt': 'secret'}}
        with patch.object(server.GENERATION, 'job', job), patch.dict(server.GENERATION.jobs, {job['id']: job}), patch('generation.availability', return_value=(True, '')):
            for path in ('/api/generation', '/api/generation?summary=1'):
                self.assertEqual(self.request('GET', path)[2]['job'], {'state': 'complete', 'step': 4, 'total': 4})
            self.assertEqual(self.request('GET', '/api/generation?job=' + job['id'])[2]['job']['result']['effectivePrompt'], 'secret')
            self.assertNotIn('result', self.request('GET', '/api/generation?summary=1&job=' + job['id'])[2]['job'])


if __name__ == '__main__':
    unittest.main()
