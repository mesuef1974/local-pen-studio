"""HTTP handler contract: local-only access, bounded bodies, private job results, logged failures."""
import http.client
import importlib.util
import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flux_server_http_test', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class StartupTests(unittest.TestCase):
    def test_a_second_studio_cannot_share_a_served_port(self):
        with server.StudioServer(('127.0.0.1', 0), server.Handler) as first:
            with self.assertRaises(OSError):
                server.StudioServer(('127.0.0.1', first.server_port), server.Handler).server_close()

    def test_path_source_must_really_be_png(self):
        import base64
        import pen_paths
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'white').save(buffer, 'TIFF')
        disguised = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        with self.assertRaises(ValueError):
            pen_paths.extract_paths({'image': disguised})


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

    def test_shared_identity_stylesheets_and_fonts_are_served_with_their_types(self):
        root = Path(server.__file__).resolve().parent.parent
        font = next((root / 'assets/fonts').glob('*.woff2')).name
        for path, kind in (('/typography.css?v=1', 'text/css'), ('/assets/fonts/fonts.css', 'text/css'), ('/assets/fonts/' + font, 'font/woff2')):
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            try:
                connection.request('GET', path, headers={'Host': f'127.0.0.1:{self.port}'})
                response = connection.getresponse()
                body = response.read()
            finally:
                connection.close()
            self.assertEqual((response.status, response.getheader('Content-Type').split(';')[0]), (200, kind), path)
            self.assertTrue(body)
        self.assertEqual(self.request('GET', '/assets/fonts/../server.py')[0], 404)

    def test_brand_icons_manifest_and_tokens_are_served_with_their_types(self):
        manifest = json.loads((server.BRAND / 'site.webmanifest').read_text(encoding='utf-8'))
        expected = {'/favicon.svg': 'image/svg+xml', '/favicon.ico': 'image/x-icon', '/apple-touch-icon.png': 'image/png', '/site.webmanifest': 'application/manifest+json', '/brand/masar/identity/tokens/tokens.css': 'text/css', '/brand/masar/identity/fonts/Almarai-Regular.ttf': 'font/ttf'}
        expected.update({icon['src']: 'image/png' for icon in manifest['icons']})
        for path, kind in expected.items():
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            try:
                connection.request('GET', path, headers={'Host': f'127.0.0.1:{self.port}'})
                response = connection.getresponse()
                body = response.read()
            finally:
                connection.close()
            self.assertEqual((response.status, response.getheader('Content-Type').split(';')[0]), (200, kind), path)
            self.assertTrue(body)

    def test_refusal_reads_a_small_body_first_and_closes_on_a_large_one(self):
        # An unread body makes Windows reset the connection on close, which can beat the refusal to the client.
        def refuse(length, body):
            handler = server.Handler.__new__(server.Handler)
            handler.headers = {'Content-Length': length}
            handler.rfile, handler.close_connection = io.BytesIO(body), False
            with patch.object(server.Handler, 'reply') as reply:
                handler.refuse(403, 'x')
            return handler.rfile.tell(), handler.close_connection, reply.call_args.args
        self.assertEqual(refuse('12', b'{"job": "x"}'), (12, False, (403, {'error': 'x'})))
        self.assertEqual(refuse('70000', b'a' * 70_000), (0, True, (403, {'error': 'x'})))
        self.assertEqual(refuse('abc', b'{}'), (0, True, (403, {'error': 'x'})))

    def test_cancel_needs_the_job_id_and_reports_whether_it_applied(self):
        self.assertEqual(self.request('POST', '/api/generation/cancel', body='{}')[0], 400)
        self.assertEqual(self.request('POST', '/api/generation/cancel', body='{"job": 5}')[0], 400)
        self.assertEqual(self.request('POST', '/api/generation/cancel', body='{"job": "x"}', origin='http://evil.example')[0], 403)
        with patch.object(server.GENERATION, 'cancel', return_value={'cancelled': True}) as cancel:
            self.assertEqual(self.request('POST', '/api/generation/cancel', body=json.dumps({'job': 'a' * 32}))[2], {'cancelled': True})
        cancel.assert_called_once_with('a' * 32)
        self.assertEqual(self.request('POST', '/api/generation/cancel', body='{"job": "unknown"}')[2], {'cancelled': False})


if __name__ == '__main__':
    unittest.main()
