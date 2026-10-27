"""Bounded local workers. Windows venv launchers can own a second Python process."""
import os
import subprocess

def terminate_tree(process):
    if process.poll() is not None:return
    if os.name=='nt':
        try:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                           timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired):pass
    else:process.kill()
    if process.poll() is None:process.kill()

def run_bounded(command,*,input,timeout):
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        stdout,stderr=process.communicate(input=input,timeout=timeout)
        return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
    except BaseException:
        terminate_tree(process)
        process.communicate(timeout=5)
        raise
