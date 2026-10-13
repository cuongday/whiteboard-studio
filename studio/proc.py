"""Child processes of the running job, so a cancel can kill them (ffmpeg, renderer, Remotion)."""
import subprocess
import threading

_LIVE: set[subprocess.Popen] = set()
_LOCK = threading.Lock()

def popen(cmd, **kw) -> subprocess.Popen:
    p = subprocess.Popen(cmd, **kw)
    with _LOCK:
        _LIVE.add(p)
    return p

def done(p: subprocess.Popen) -> None:
    with _LOCK:
        _LIVE.discard(p)

def run(cmd, **kw) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True) that a cancel can kill."""
    p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
    try:
        out, err = p.communicate()
    finally:
        done(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)

def kill_all() -> None:
    with _LOCK:
        live = list(_LIVE)
    for p in live:
        try:
            p.kill()
        except OSError:
            pass
