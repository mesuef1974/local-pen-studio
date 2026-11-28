"""Forward the account and project API to the local Masar server, so the studio page stays on one origin."""
import http.client
import os
import re

UPSTREAM_PORT = int(os.environ.get('MASAR_UPSTREAM_PORT', '8780'))
# Only these API groups leave the studio. Segments cannot hold dots or percent escapes, so nothing climbs out.
ROUTE = re.compile(r'/api/(auth|users|audit|projects|assets)(/[A-Za-z0-9-]+)*')
QUERY = re.compile(r'[A-Za-z0-9=&-]*')
REQUEST_HEADERS = ('Host', 'Origin', 'Cookie', 'Content-Type', 'X-CSRFToken')
RESPONSE_HEADERS = {'content-type', 'content-disposition', 'set-cookie', 'vary'}


def matches(path):
    return ROUTE.fullmatch(path) is not None


def body_limit(path):
    """Mirrors masar-server: raw images and project state are the only large bodies."""
    if path == '/api/assets':
        return 32 * 1024 * 1024
    if path.startswith('/api/projects/') and path.endswith('/state'):
        return 16 * 1024 * 1024
    return 64 * 1024


def verify(headers):
    """The account server's verdict on this request's session and CSRF token: 204 means go ahead."""
    return forward('POST', '/api/auth/verify', '', headers, b'')[0]


def forward(method, path, query, headers, body=None):
    """Return (status, header pairs, body). Raises OSError or HTTPException when the account server is away."""
    sent = {name: headers[name] for name in REQUEST_HEADERS if headers.get(name) is not None}
    if body is not None:
        sent['Content-Length'] = str(len(body))
    target = f'{path}?{query}' if query and QUERY.fullmatch(query) else path
    connection = http.client.HTTPConnection('127.0.0.1', UPSTREAM_PORT, timeout=30)
    try:
        connection.request(method, target, body=body, headers=sent)
        response = connection.getresponse()
        kept = [(name, value) for name, value in response.getheaders() if name.lower() in RESPONSE_HEADERS]
        return response.status, kept, response.read()
    finally:
        connection.close()
