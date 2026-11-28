class ResponseHeadersMiddleware:
    """The API serves JSON only: nothing may be cached, framed or executed."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
        return response
