import queue
import threading
from studio import jobs, pipeline

def _wait(runner, q, types, timeout=5):
    while True:
        ev = q.get(timeout=timeout)
        if ev["type"] in types:
            return ev

def test_factory_raises_resets_busy_and_emits_error():
    def boom(): raise RuntimeError("no deps")
    r = jobs.JobRunner(deps_factory=boom)
    q = r.subscribe()
    assert r.submit("p1", "segment")
    ev = _wait(r, q, {"error"})
    assert ev["type"] == "error" and r.busy is False

def test_busy_false_when_done_received(monkeypatch):
    monkeypatch.setattr(pipeline, "run_segment", lambda pid, deps, **kw: None)
    r = jobs.JobRunner(deps_factory=pipeline.Deps)
    q = r.subscribe()
    assert r.submit("p1", "segment")
    _wait(r, q, {"done"})
    assert r.busy is False

def test_submit_while_busy_returns_false(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(pipeline, "run_segment", lambda pid, deps, **kw: gate.wait(5))
    r = jobs.JobRunner(deps_factory=pipeline.Deps)
    q = r.subscribe()
    assert r.submit("p1", "segment")
    assert r.submit("p1", "segment") is False
    gate.set()
    _wait(r, q, {"done"})
