from django.http import HttpResponse


class ResponseHeadersMiddleware:
    """Nothing may be cached or framed. The API runs nothing; the admin runs only its own files."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        policy = "default-src 'none'; frame-ancestors 'none'"
        if request.path.startswith(('/admin/', '/static/')):
            policy = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                      "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        response['Content-Security-Policy'] = policy
        return response


class RefuseMultipartMiddleware:
    """No endpoint takes multipart, and the CSRF check would spool its files to disk before authentication."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.content_type.startswith('multipart/'):
            return HttpResponse(status=415)
        return self.get_response(request)
