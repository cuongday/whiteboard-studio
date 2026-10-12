import queue
import threading
from . import pipeline, store

class JobRunner:
    def __init__(self, deps_factory=pipeline.Deps):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self.busy = False
        self.pid: str | None = None
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
        try:
            threading.Thread(target=self._run, args=(pid, kind, kw), daemon=True).start()
        except BaseException:
            self.busy = False; self.pid = None
            raise
        return True

    def _run(self, pid, kind, kw):
        ev: dict
        try:
            deps = self.deps_factory()
            deps.progress = lambda msg, pct: self.emit({"pid": pid, "type": "progress", "msg": msg, "pct": round(pct, 3)})
            fn = {"segment": pipeline.run_segment, "images": pipeline.run_images, "render": pipeline.run_render}[kind]
            fn(pid, deps, **kw)
            ev = {"pid": pid, "type": "done", "msg": kind, "pct": 1}
        except Exception as e:  # noqa: BLE001
            try:
                p = store.load(pid); p.job_error = str(e); store.save(p)
            except Exception:  # noqa: BLE001
                pass
            ev = {"pid": pid, "type": "error", "msg": str(e), "pct": 0}
        finally:
            self.busy = False; self.pid = None
        self.emit(ev)

JOBS = JobRunner()
