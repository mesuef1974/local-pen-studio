"""Launch the separate three-stage local pipeline."""
from pathlib import Path
import json,subprocess,sys,time,urllib.request,webbrowser
URL='http://127.0.0.1:8769'
def ready():
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/api/status',timeout=1) as r:return json.load(r).get('service')=='pipeline-studio'
    except (OSError,ValueError):return False
if __name__=='__main__':
    if not ready():
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(40):
            if ready():break
            if process.poll() is not None:raise SystemExit('Port 8769 may be occupied. Run server.py for details.')
            time.sleep(.1)
        else:raise SystemExit('Could not start the pipeline server.')
    webbrowser.open(URL+'/prepare')
