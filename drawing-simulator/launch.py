"""Start the loopback simulator, then open the user's browser."""
from pathlib import Path
import json,subprocess,sys,time,urllib.request,webbrowser

URL='http://127.0.0.1:8765'
def ready():
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/api/status',timeout=1) as response:
            return json.load(response).get('service')=='drawing-simulator'
    except (OSError,ValueError):return False

if __name__=='__main__':
    if not ready():
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(30):
            if ready():break
            if process.poll() is not None:raise SystemExit('Could not start: port 8765 may be in use. Run server.py for details.')
            time.sleep(.1)
        else:raise SystemExit('Server startup timed out. Run server.py for details.')
    webbrowser.open(URL)
