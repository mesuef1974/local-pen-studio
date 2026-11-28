"""The studio forwards only the account API, keeps its origin check, and survives a missing account server."""
import http.client
import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flux_server_proxy_test', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
proxy = server.account_proxy

SEEN = []


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        SEEN.append((self.command, self.path, dict(self.headers), body))
        raw = b'{"ok":true}'
        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'csrftoken=a')
        self.send_header('Set-Cookie', 'masar_session=b')
        self.send_header('X-Internal', 'secret')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = answer


def serve(handler):
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream, cls.studio = serve(Upstream), serve(server.Handler)
        cls.port = cls.studio.server_port

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.upstream, cls.studio):
            httpd.shutdown()
            httpd.server_close()

    def setUp(self):
        SEEN.clear()
        patcher = patch.object(proxy, 'UPSTREAM_PORT', self.upstream.server_port)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, method, path, body=None, origin=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        sent = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(headers or {})}
        if origin:
            sent['Origin'] = f'http://127.0.0.1:{self.port}'
        try:
            connection.request(method, path, body=body, headers=sent)
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def test_post_keeps_origin_session_and_both_cookies(self):
        status, headers, raw = self.request('POST', '/api/auth/login', b'{"a":1}',
                                            headers={'Cookie': 'c=1', 'X-CSRFToken': 't', 'Authorization': 'x'})
        self.assertEqual((status, raw), (201, b'{"ok":true}'))
        self.assertEqual([v for k, v in headers if k == 'Set-Cookie'], ['csrftoken=a', 'masar_session=b'])
        self.assertNotIn('X-Internal', dict(headers))
        self.assertIn('Content-Security-Policy', dict(headers))
        method, path, received, body = SEEN[0]
        self.assertEqual((method, path, body), ('POST', '/api/auth/login', b'{"a":1}'))
        self.assertEqual((received['Host'], received['Cookie'], received['X-CSRFToken']),
                         (f'127.0.0.1:{self.port}', 'c=1', 't'))
        self.assertNotIn('Authorization', received)

    def test_get_forwards_a_plain_query(self):
        self.assertEqual(self.request('GET', '/api/audit?limit=5', origin=False)[0], 201)
        self.assertEqual(SEEN[0][1], '/api/audit?limit=5')

    def test_foreign_origin_and_unlisted_paths_stay_local(self):
        self.assertEqual(self.request('POST', '/api/auth/login', b'{}', origin=False)[0], 403)
        for path in ('/api/projects/../status', '/api/authx', '/api/auth/%2e%2e', '/api/admin'):
            self.assertEqual(self.request('GET', path)[0], 404, path)
        self.assertEqual(SEEN, [])

    def test_oversized_body_is_refused(self):
        self.assertEqual(self.request('POST', '/api/auth/login', b'x' * (64 * 1024 + 1))[0], 413)
        self.assertEqual(SEEN, [])
        self.assertEqual(proxy.body_limit('/api/assets'), 32 * 1024 * 1024)
        self.assertEqual(proxy.body_limit('/api/projects/abc/state'), 16 * 1024 * 1024)

    def test_missing_account_server_is_reported(self):
        closed = serve(Upstream)
        port = closed.server_port
        closed.shutdown()
        closed.server_close()
        with patch.object(proxy, 'UPSTREAM_PORT', port):
            status, _, raw = self.request('GET', '/api/auth/me')
        self.assertEqual((status, json.loads(raw)['code']), (503, 'accounts_unavailable'))


if __name__ == '__main__':
    unittest.main()
