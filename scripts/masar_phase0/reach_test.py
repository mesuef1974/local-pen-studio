"""Masar phase 0: can teacher devices reach this machine over the school network?

Serves one fixed page (no files, no uploads, no data) and stops by itself after 15 minutes.
The owner runs it:  python scripts/masar_phase0/reach_test.py
Windows may ask to allow Python through the firewall; that choice is the owner's.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8790
MINUTES = 15
PAGE = ('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>اختبار الوصول</title>'
        '<body style="font:24px sans-serif;text-align:center"><h1>وصلتَ إلى جهاز مسار</h1>').encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        found = self.path == '/'
        body = PAGE if found else b''
        self.send_response(200 if found else 404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        if self.path == '/':
            print(f'reached from {self.client_address[0]}', flush=True)


def addresses():
    found = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    return sorted(a for a in found if not a.startswith(('127.', '169.254.')))


def main():
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    for address in addresses():
        print(f'try from a teacher device:  http://{address}:{PORT}/')
    print(f'stops after {MINUTES} minutes, or press Ctrl+C', flush=True)
    timer = threading.Timer(MINUTES * 60, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
