"""Browser smoke test: import, approval, pen paths and both exports in a real browser. No FLUX generation, no GPU.

Run with: python flux-studio/browser_smoke.py [--channel msedge|chrome]
Not named test_*.py on purpose: unittest discovery must not require Playwright.
"""
import argparse
import importlib.util
import sys
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('flux_server_smoke', HERE / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SignedIn(BaseHTTPRequestHandler):
    """Stands in for the account server: this walk is about the studio, behind the sign-in."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = b'{"must_change_password":false}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.send_response(204)
        self.end_headers()


def check_svg(path):
    root = ET.parse(path).getroot()
    assert (root.get('width'), root.get('height')) == ('210mm', '297mm'), 'export is not A4'
    assert root.findall('.//{*}path'), 'export has no paths'


def run(page, url):
    page.goto(url + '/prepare')
    page.locator('#sampleInk').click()
    forward = page.locator('#next')
    expect(forward).to_be_enabled()
    forward.click()
    page.wait_for_url('**/review')
    expect(forward).to_be_disabled()  # approval needs the whole checklist
    for index in range(4):
        page.locator(f'#check{index}').check()
    forward.click()
    page.wait_for_url('**/paths')
    expect(forward).to_be_enabled(timeout=90_000)
    forward.click()
    page.wait_for_url('**/output')
    expect(forward).to_be_enabled()
    with page.expect_download() as pen:
        forward.click()
    check_svg(pen.value.path())
    page.locator('#toolLaser').click()
    expect(forward).to_be_enabled()
    with page.expect_download() as laser:
        forward.click()
    check_svg(laser.value.path())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='msedge' if sys.platform == 'win32' else 'chrome',
                        help='installed browser to drive; no browser is downloaded')
    channel = parser.parse_args().channel
    accounts = ThreadingHTTPServer(('127.0.0.1', 0), SignedIn)
    threading.Thread(target=accounts.serve_forever, daemon=True).start()
    server.account_proxy.UPSTREAM_PORT = accounts.server_port
    studio = server.StudioServer(('127.0.0.1', 0), server.Handler)
    threading.Thread(target=studio.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: message.type == 'error' and errors.append(message.text))
                run(page, f'http://127.0.0.1:{studio.server_port}')
                assert not errors, f'browser errors: {errors}'
            finally:
                browser.close()
    finally:
        studio.shutdown()
        studio.server_close()
        accounts.shutdown()
        accounts.server_close()
    print('Browser smoke test passed.')


if __name__ == '__main__':
    main()
