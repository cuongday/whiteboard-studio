import os
import queue
import threading
import time
from . import pipeline, store

class JobRunner:
    def __init__(self, deps_factory=pipeline.Deps):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self.busy = False
        self.pid: str | None = None
        self.kind: str | None = None
        self.started_at: float | None = None
        self.last_progress: dict | None = None
        self.deps_factory = deps_factory

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(); self._subs.append(q); return q

    def unsubscribe(self, q) -> None:
        if q in self._subs: self._subs.remove(q)

    def emit(self, ev: dict) -> None:
        for q in list(self._subs): q.put(ev)

    def submit(self, pid: str, kind: str, **kw) -> bool:
        with self._lock:
            if self.busy: return False
            self.busy = True
            self.pid = pid
            self.kind = kind
            self.started_at = time.time()
            self.last_progress = None
        try:
            threading.Thread(target=self._run, args=(pid, kind, kw), daemon=True).start()
        except BaseException:
            self.busy = False; self.pid = None
            raise
        return True

    def _run(self, pid, kind, kw):
        ev: dict
        lock = store.project_dir(pid) / ".job.pid"
        try:
            lock.write_text(str(os.getpid()))
        except OSError:
            pass
        try:
            deps = self.deps_factory()
            def progress(msg, pct):
                ev = {"pid": pid, "type": "progress", "msg": msg, "pct": round(pct, 3)}
                self.last_progress = ev
                self.emit(ev)
            deps.progress = progress
            fn = {"segment": pipeline.run_segment, "images": pipeline.run_images, "render": pipeline.run_render,
                  "compose": pipeline.run_compose, "rebuild_scene": pipeline.run_rebuild_scene,
                  "new_version": pipeline.run_new_version}[kind]
            fn(pid, deps, **kw)
            ev = {"pid": pid, "type": "done", "msg": kind, "pct": 1}
        except Exception as e:  # noqa: BLE001
            try:
                p = store.load(pid); p.job_error = str(e); store.save(p)
            except Exception:  # noqa: BLE001
                pass
            ev = {"pid": pid, "type": "error", "msg": str(e), "pct": 0}
        finally:
            lock.unlink(missing_ok=True)
            self._record_time(pid, kind)
            self.busy = False; self.pid = None; self.kind = None; self.started_at = None; self.last_progress = None
        ev["seconds"] = self.last_seconds
        self.emit(ev)

    last_seconds: float | None = None

    def _record_time(self, pid, kind):
        self.last_seconds = round(time.time() - (self.started_at or time.time()), 1)
        try:
            p = store.load(pid); p.timings[kind] = self.last_seconds; store.save(p)
        except Exception:  # noqa: BLE001
            pass

JOBS = JobRunner()


def job_alive_elsewhere(pdir) -> bool:
    """True if another live server process is running a job on this project dir."""
    try:
        other = int((pdir / ".job.pid").read_text())
    except (OSError, ValueError):
        return False
    if other == os.getpid():
        return False
    try:
        os.kill(other, 0)
        return True
    except OSError:
        return False
