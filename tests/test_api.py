import time
from fastapi.testclient import TestClient
from studio import app as app_mod, jobs, store
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
    assert c.get(f"/api/projects/{pid}").json()["stage"] == "done"
    assert c.get(f"/api/projects/{pid}/files/final.mp4").content == b"final"

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
