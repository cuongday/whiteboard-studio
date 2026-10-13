import time
from fastapi.testclient import TestClient
from studio import app as app_mod, jobs, store, versions
from tests.test_pipeline import deps

def client(monkeypatch):
    runner = jobs.JobRunner(deps_factory=deps)
    monkeypatch.setattr(app_mod, "JOBS", runner)
    return TestClient(app_mod.app), runner

def wait(runner):
    for _ in range(100):
        if not runner.busy: return
        time.sleep(0.05)
    raise AssertionError("job stuck")

def test_create_from_upload_and_flow(monkeypatch):
    c, r = client(monkeypatch)
    res = c.post("/api/projects", data={"title": "T", "aspect": "9:16", "voice": "Hải Đăng",
                                        "captions": "true", "music": "false"},
                 files={"file": ("k.srt", "1\n00:00:01,000 --> 00:00:02,000\nGiá tăng.\n".encode(), "text/plain")})
    assert res.status_code == 200
    pid = res.json()["id"]; wait(r)
    p = c.get(f"/api/projects/{pid}").json()
    assert p["stage"] == "scenes" and p["source_text"] == "Giá tăng."
    scenes = p["scenes"]; scenes[0]["visual_description"] = "new picture"
    p2 = c.put(f"/api/projects/{pid}/scenes", json=scenes).json()
    assert "new picture" in p2["scenes"][0]["image_prompt"]
    assert c.post(f"/api/projects/{pid}/approve/scenes").status_code == 200; wait(r)
    assert c.get(f"/api/projects/{pid}/files/scenes/01/image.png").status_code == 200
    assert c.post(f"/api/projects/{pid}/render").status_code == 200; wait(r)
    p = c.get(f"/api/projects/{pid}").json()
    assert p["stage"] == "done" and p["final"] == "versions/v1/final.mp4"
    assert c.get(f"/api/projects/{pid}/files/{p['final']}").content == b"final"

def test_busy_and_traversal(monkeypatch):
    c, r = client(monkeypatch)
    pid = c.post("/api/projects", data={"title": "T", "text": "abc", "aspect": "16:9"}).json()["id"]
    wait(r)
    r.busy = True
    assert c.post(f"/api/projects/{pid}/render").status_code == 409
    r.busy = False
    assert c.get(f"/api/projects/{pid}/files/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)

def test_requires_input(monkeypatch):
    c, _ = client(monkeypatch)
    assert c.post("/api/projects", data={"title": "T"}).status_code == 400


def _mk(c, r):
    pid = c.post("/api/projects", data={"title": "T", "text": "abc", "aspect": "16:9"}).json()["id"]
    wait(r)
    return pid

def test_edits_rejected_while_busy(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    p = c.get(f"/api/projects/{pid}").json()
    r.busy = True
    assert c.put(f"/api/projects/{pid}/scenes", json=p["scenes"]).status_code == 409
    assert c.put(f"/api/projects/{pid}/settings", json=p["settings"]).status_code == 409
    r.busy = False

def test_bad_pid_404(monkeypatch):
    c, _ = client(monkeypatch)
    assert c.get("/api/projects/..").status_code == 404
    assert c.get("/api/projects/zzzzzzzzzz").status_code == 404

def test_corrupt_upload_400(monkeypatch):
    c, _ = client(monkeypatch)
    res = c.post("/api/projects", data={"title": "T"}, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert res.status_code == 400

def test_reset_stale(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    p = store.load(pid)
    p.stage = "rendering"; p.scenes[0].status["image"] = "running"; store.save(p)
    bad = store.project_dir("deadbeef00"); bad.mkdir(parents=True)
    (bad / "project.json").write_text("{corrupt")
    app_mod.reset_stale()
    p = store.load(pid)
    assert p.stage == "images" and p.scenes[0].status["image"] == "pending"

def _flow_to_images(c, r):
    pid = c.post("/api/projects", data={"title": "T", "text": "Giá tăng. Tiền giảm.", "aspect": "16:9"}).json()["id"]
    wait(r)
    c.post(f"/api/projects/{pid}/approve/scenes"); wait(r)
    return pid

def test_renumbering_moves_dirs(monkeypatch):
    c, r = client(monkeypatch)
    pid = _flow_to_images(c, r)
    p = c.get(f"/api/projects/{pid}").json()
    assert [s["id"] for s in p["scenes"]] == ["01", "02"]
    (store.project_dir(pid) / "scenes" / "02" / "marker.txt").write_text("B")
    res = c.put(f"/api/projects/{pid}/scenes", json=[p["scenes"][1]]).json()
    assert [s["id"] for s in res["scenes"]] == ["01"]
    assert res["scenes"][0]["status"]["image"] == "done"
    sd = store.project_dir(pid) / "scenes"
    assert (sd / "01" / "marker.txt").read_text() == "B"
    assert not (sd / "02").exists()

def test_client_status_ignored(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    sc = c.get(f"/api/projects/{pid}").json()["scenes"][0]
    sc["id"] = "new"; sc["status"] = {"image": "done", "voice": "done", "draw": "done"}
    res = c.put(f"/api/projects/{pid}/scenes", json=[sc]).json()
    assert res["scenes"][0]["status"] == {"image": "pending", "voice": "pending", "draw": "pending"}

def test_elements_only_change(monkeypatch):
    c, r = client(monkeypatch)
    pid = _flow_to_images(c, r)
    sc = c.get(f"/api/projects/{pid}").json()["scenes"]
    sc[0]["elements"] = [{"label": "x", "say": "y"}]
    res = c.put(f"/api/projects/{pid}/scenes", json=sc).json()["scenes"][0]
    assert res["status"]["image"] == "done" and res["status"]["draw"] == "pending"

def test_regenerate_busy_no_mutation(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    before = store.load(pid).scenes[0].image_prompt
    r.busy = True
    assert c.post(f"/api/projects/{pid}/scenes/01/regenerate", json={"image_prompt": "zzz"}).status_code == 409
    r.busy = False
    assert store.load(pid).scenes[0].image_prompt == before

def test_jobs_endpoint_and_resegment(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    assert c.get("/api/jobs").json() == {"busy": False, "pid": None, "kind": None, "started_at": None, "progress": None}
    r.busy = True; r.pid = pid; r.kind = "render"; r.started_at = 100.0
    r.last_progress = {"pid": pid, "type": "progress", "msg": "Vẽ", "pct": 0.5}
    assert c.get("/api/jobs").json() == {"busy": True, "pid": pid, "kind": "render", "started_at": 100.0,
                                         "progress": {"pid": pid, "type": "progress", "msg": "Vẽ", "pct": 0.5}}
    assert c.post(f"/api/projects/{pid}/segment").status_code == 409
    r.busy = False; r.pid = None; r.kind = None; r.started_at = None
    assert c.post(f"/api/projects/{pid}/segment").status_code == 200; wait(r)
    assert "segment" in c.get(f"/api/projects/{pid}").json()["timings"]
    assert store.load(pid).stage == "scenes"
    c.post(f"/api/projects/{pid}/approve/scenes"); wait(r)
    assert c.post(f"/api/projects/{pid}/segment").status_code == 409

def test_settings_voice_change_invalidates_done_project(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    c.post(f"/api/projects/{pid}/approve/scenes"); wait(r)
    c.post(f"/api/projects/{pid}/render"); wait(r)
    p = c.get(f"/api/projects/{pid}").json()
    assert p["stage"] == "done"
    st = dict(p["settings"]); st["voice"] = "Giọng Khác"
    out = c.put(f"/api/projects/{pid}/settings", json=st).json()
    assert out["stage"] == "images" and out["final"] is None
    assert all(s["status"]["voice"] == "pending" for s in out["scenes"])

def test_settings_ignores_client_music_file(monkeypatch):
    c, r = client(monkeypatch)
    pid = _mk(c, r)
    st = dict(c.get(f"/api/projects/{pid}").json()["settings"]); before = st["music_file"]
    st["music_file"] = "../../etc/passwd"
    out = c.put(f"/api/projects/{pid}/settings", json=st).json()
    assert out["settings"]["music_file"] == before

def test_music_upload_bad_suffix(monkeypatch):
    c, r = client(monkeypatch)
    res = c.post("/api/projects", data={"title": "T", "text": "abc"},
                 files={"music_file": ("x.exe", b"MZ", "application/octet-stream")})
    assert res.status_code == 400

def test_reset_stale_skips_project_running_elsewhere(monkeypatch):
    import os, subprocess, sys
    from studio.models import Settings, Scene
    p = store.create_project("t", Settings(), "x")
    p.scenes = [Scene(id="01", text="a", status={"image": "done", "voice": "pending", "draw": "pending"})]
    store.save(p); p = store.load(p.id)
    from studio import versions
    versions.get(p).scenes["01"].status["voice"] = "running"
    p.stage = "rendering"; store.save(p)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (store.project_dir(p.id) / ".job.pid").write_text(str(other.pid))
        app_mod.reset_stale()
        q = store.load(p.id)
        assert q.stage == "rendering" and versions.get(q).scenes["01"].status["voice"] == "running"
    finally:
        other.kill(); other.wait()
    app_mod.reset_stale()   # owner gone -> stale state is reset
    assert store.load(p.id).stage == "images"

def test_models_endpoint_and_validation(monkeypatch):
    c, r = client(monkeypatch)
    m = c.get("/api/models").json()
    assert {"gemini-2.5-flash", "gemini-3.8-flash"} <= {x["id"] for x in m["text"]}
    assert "gemini-3-pro-image" in {x["id"] for x in m["image"]}
    res = c.post("/api/projects", data={"title": "T", "text": "abc", "text_model": "gpt-4"})
    assert res.status_code == 400
    res = c.post("/api/projects", data={"title": "T", "text": "abc", "text_model": "gemini-3.8-flash",
                                        "image_model": "gemini-3-pro-image"})
    pid = res.json()["id"]; wait(r)
    p = c.get(f"/api/projects/{pid}").json()
    assert (p["settings"]["text_model"], p["settings"]["image_model"]) == ("gemini-3.8-flash", "gemini-3-pro-image")
    assert c.post(f"/api/projects/{pid}/approve/scenes").status_code == 200; wait(r)
    assert c.post(f"/api/projects/{pid}/scenes/01/regenerate", json={"image_model": "nope"}).status_code == 400
    assert c.post(f"/api/projects/{pid}/scenes/01/regenerate",
                  json={"image_model": "gemini-3.1-flash-lite-image"}).status_code == 200; wait(r)
    sc = c.get(f"/api/projects/{pid}").json()["scenes"]
    assert sc[0]["image_model"] == "gemini-3.1-flash-lite-image"

def _done(c, r):
    pid = _flow_to_images(c, r)
    c.post(f"/api/projects/{pid}/render"); wait(r)
    return pid

def test_scene_edit_invalidation(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    v = lambda: versions.get(store.load(pid)).scenes["01"]   # noqa: E731
    out = c.put(f"/api/projects/{pid}/scenes/01", json={"narration": "Gia tăng."}).json()
    assert out["scenes"][0]["narration"] == "Gia tăng." and v().status == {"voice": "pending", "draw": "pending"}
    c.post(f"/api/projects/{pid}/versions/v1/scenes/01/rebuild"); wait(r)
    assert v().status == {"voice": "done", "draw": "done"} and v().composed is False
    c.put(f"/api/projects/{pid}/scenes/01", json={"text": "Giá tăng mạnh."})        # narration set -> subtitle only
    assert v().status == {"voice": "done", "draw": "pending"}
    c.post(f"/api/projects/{pid}/versions/v1/scenes/01/rebuild"); wait(r)
    c.put(f"/api/projects/{pid}/scenes/01", json={"elements": [{"label": "b", "say": "mạnh"}, {"label": "a", "say": "Giá"}]})
    assert v().status == {"voice": "done", "draw": "pending"}
    assert store.load(pid).stage == "done"

def test_compose_and_versions(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    c.put(f"/api/projects/{pid}/scenes/02", json={"text": "Tiền giảm mạnh."})
    assert c.post(f"/api/projects/{pid}/versions/v1/compose").status_code == 200; wait(r)
    p = store.load(pid)
    assert all(vs.composed for vs in versions.get(p, "v1").scenes.values())
    assert c.post(f"/api/projects/{pid}/versions", json={"voice": "Mai Anh"}).status_code == 200; wait(r)
    p = c.get(f"/api/projects/{pid}").json()
    assert [v["id"] for v in p["versions"]] == ["v1", "v2"] and p["active_version"] == "v2"
    assert p["final"] == "versions/v2/final.mp4"
    p = c.put(f"/api/projects/{pid}/active_version", json={"id": "v1"}).json()
    assert p["final"] == "versions/v1/final.mp4"
    assert c.put(f"/api/projects/{pid}/active_version", json={"id": "v9"}).status_code == 404

def test_per_scene_voice_only_that_version(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    c.post(f"/api/projects/{pid}/versions", json={"voice": "Mai Anh"}); wait(r)
    c.put(f"/api/projects/{pid}/versions/v2/scenes/01", json={"voice": "Thiện Minh"})
    p = store.load(pid)
    assert versions.get(p, "v2").scenes["01"].voice == "Thiện Minh"
    assert versions.get(p, "v2").scenes["01"].status["voice"] == "pending"
    assert versions.get(p, "v1").scenes["01"].status["voice"] == "done"

def test_new_endpoints_busy_409(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    r.busy = True
    for method, url, body in [("put", f"/api/projects/{pid}/scenes/01", {"text": "x"}),
                              ("put", f"/api/projects/{pid}/versions/v1/scenes/01", {"voice": "x"}),
                              ("post", f"/api/projects/{pid}/versions/v1/scenes/01/rebuild", None),
                              ("post", f"/api/projects/{pid}/versions/v1/compose", None),
                              ("post", f"/api/projects/{pid}/versions", {"voice": "x"}),
                              ("put", f"/api/projects/{pid}/active_version", {"id": "v1"})]:
        res = getattr(c, method)(url, json=body) if body is not None else getattr(c, method)(url)
        assert res.status_code == 409, url
    r.busy = False

def test_listen(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    from studio import voice as voice_mod
    def fake(text, v, out, tts=None, timeout=None):
        out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(b"RIFF"); return []
    monkeypatch.setattr(voice_mod, "synthesize", fake)
    res = c.post(f"/api/projects/{pid}/scenes/01/listen", json={"narration": "ây pi ai", "voice": "Hải Đăng"}).json()
    assert res["url"].startswith(f"/api/projects/{pid}/files/tmp/listen-01.wav")
    def busy(*a, **k): raise TimeoutError()
    monkeypatch.setattr(voice_mod, "synthesize", busy)
    assert c.post(f"/api/projects/{pid}/scenes/01/listen", json={"narration": "a", "voice": "Hải Đăng"}).status_code == 503

def test_unchanged_scene_save_keeps_done(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    sc = c.get(f"/api/projects/{pid}").json()["scenes"]
    out = c.put(f"/api/projects/{pid}/scenes", json=sc).json()
    assert out["stage"] == "done" and out["final"] == "versions/v1/final.mp4"

def test_reset_stale_keeps_done_when_final_exists(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    p = store.load(pid); p.stage = "rendering"; store.save(p)
    app_mod.reset_stale()
    assert store.load(pid).stage == "done"

def test_pen_text_create_preview_and_settings(monkeypatch, tmp_path):
    from studio import hand as hand_mod
    monkeypatch.setattr(hand_mod, "CACHE", tmp_path)
    c, r = client(monkeypatch)
    res = c.get("/api/hand", params={"text": "Kênh Của Tôi", "color": "#1f5bff"})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png" and res.content[:4] == b"\x89PNG"
    assert c.get("/api/hand").status_code == 200                       # plain marker
    pid = c.post("/api/projects", data={"title": "T", "text": "Giá tăng. Tiền giảm.", "pen_text": "  Kênh   A ",
                                        "pen_color": "nope"}).json()["id"]; wait(r)
    st = c.get(f"/api/projects/{pid}").json()["settings"]
    assert (st["pen_text"], st["pen_color"]) == ("Kênh A", hand_mod.DEFAULT_COLOR)
    c.post(f"/api/projects/{pid}/approve/scenes"); wait(r)
    c.post(f"/api/projects/{pid}/render"); wait(r)
    st["pen_text"] = "Kênh B"
    out = c.put(f"/api/projects/{pid}/settings", json=st).json()
    assert out["settings"]["pen_text"] == "Kênh B" and out["stage"] == "images"
    v = versions.get(store.load(pid))
    assert all(vs.status == {"voice": "done", "draw": "pending"} for vs in v.scenes.values())

def test_regenerate_all_images_with_model(monkeypatch):
    from tests.test_pipeline import used_models
    c, r = client(monkeypatch)
    pid = _flow_to_images(c, r)
    p = store.load(pid); p.scenes[1].status["image"] = "error"; store.save(p)
    used_models.clear()
    assert c.post(f"/api/projects/{pid}/approve/scenes", json={"image_model": "gemini-3-pro-image"}).status_code == 200; wait(r)
    assert used_models == ["gemini-3-pro-image"]                       # only the failed one
    used_models.clear()
    assert c.post(f"/api/projects/{pid}/approve/scenes",
                  json={"image_model": "gemini-3.1-flash-lite-image", "all": True}).status_code == 200; wait(r)
    assert used_models == ["gemini-3.1-flash-lite-image"] * 2
    q = store.load(pid)
    assert all(s.image_model == "gemini-3.1-flash-lite-image" and s.status["image"] == "done" for s in q.scenes)
    assert c.post(f"/api/projects/{pid}/approve/scenes", json={"image_model": "nope", "all": True}).status_code == 400

def test_regenerate_all_on_done_project_marks_redraw(monkeypatch):
    c, r = client(monkeypatch)
    pid = _done(c, r)
    assert c.post(f"/api/projects/{pid}/approve/scenes").status_code == 409          # nothing missing
    assert c.post(f"/api/projects/{pid}/approve/scenes", json={"all": True}).status_code == 200; wait(r)
    q = store.load(pid)
    assert q.stage == "done"
    assert all(vs.status == {"voice": "done", "draw": "pending"} and not vs.composed
               for vs in versions.get(q).scenes.values())

def test_compose_engine_choice(monkeypatch):
    c, r = client(monkeypatch)
    pid = c.post("/api/projects", data={"title": "T", "text": "Giá tăng.", "composer": "remotion"}).json()["id"]; wait(r)
    assert c.get(f"/api/projects/{pid}").json()["settings"]["composer"] == "remotion"
    c.post(f"/api/projects/{pid}/approve/scenes"); wait(r)
    c.post(f"/api/projects/{pid}/render"); wait(r)
    assert c.post(f"/api/projects/{pid}/versions/v1/compose", json={"composer": "ffmpeg"}).status_code == 200; wait(r)
    assert store.load(pid).settings.composer == "ffmpeg"
    assert c.post(f"/api/projects/{pid}/versions/v1/compose", json={"composer": "bogus"}).status_code == 422

def test_writes_blocked_while_job_runs_and_cancel(monkeypatch):
    import threading
    from studio import pipeline
    c, r = client(monkeypatch)
    pid = _flow_to_images(c, r)
    gate = threading.Event()
    monkeypatch.setattr(pipeline, "run_render", lambda pid, deps, **kw: (gate.wait(5), pipeline.check_cancel(deps)))
    assert c.post(f"/api/projects/{pid}/render").status_code == 200
    st = c.get(f"/api/projects/{pid}").json()["settings"]
    assert c.put(f"/api/projects/{pid}/settings", json=st).status_code == 409
    assert c.put(f"/api/projects/{pid}/scenes/01", json={"text": "x"}).status_code == 409
    assert c.post(f"/api/projects/{pid}/cancel").status_code == 200
    gate.set(); wait(r)
    assert c.post(f"/api/projects/{pid}/cancel").status_code == 409
    assert store.load(pid).job_error is None

def test_srt_delete_version_and_cleanup(monkeypatch):
    c, r = client(monkeypatch)
    pid = _flow_to_images(c, r)
    c.post(f"/api/projects/{pid}/render"); wait(r)
    srt = c.get(f"/api/projects/{pid}/versions/v1/subtitles.srt")
    assert srt.status_code == 200 and srt.text.startswith("1\n00:00:00,") and "-->" in srt.text
    assert c.delete(f"/api/projects/{pid}/versions/v1").status_code == 409        # only version
    c.post(f"/api/projects/{pid}/versions", json={"voice": "Hải Đăng"}); wait(r)
    out = c.delete(f"/api/projects/{pid}/versions/v1").json()
    assert [v["id"] for v in out["versions"]] == ["v2"] and out["active_version"] == "v2"
    assert not versions.vdir(pid, "v1").exists()
    (store.project_dir(pid) / "tmp").mkdir(exist_ok=True); (store.project_dir(pid) / "tmp" / "x.wav").write_bytes(b"x" * 10)
    assert c.get(f"/api/projects/{pid}/storage").json()["cleanable"] >= 10
    assert c.post(f"/api/projects/{pid}/cleanup").json()["cleanable"] == 0
