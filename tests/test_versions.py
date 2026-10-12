import json
from studio import store, versions
from studio.models import Scene, Settings, Element

def _legacy(tmp_files=True):
    p = store.create_project("t", Settings(voice="Hải Đăng"), "x")
    raw = json.loads((store.project_dir(p.id) / "project.json").read_text())
    raw["versions"] = []
    raw["scenes"] = [Scene(id="01", text="Giá tăng.", status={"image": "done", "voice": "done", "draw": "done"},
                           duration_ms=1500).model_dump()]
    raw["final"] = "final.mp4"; raw["stage"] = "done"
    (store.project_dir(p.id) / "project.json").write_text(json.dumps(raw))
    d = store.scene_dir(p.id, "01")
    for f in ("image.png", "voice.wav", "words.json", "clip.mp4"):
        (d / f).write_text(f)
    (store.project_dir(p.id) / "final.mp4").write_text("final")
    return p.id

def test_migrates_legacy_project_once():
    pid = _legacy()
    p = store.load(pid)
    v = versions.get(p)
    assert (v.id, v.voice, v.final) == ("v1", "Hải Đăng", "versions/v1/final.mp4")
    vs = v.scenes["01"]
    assert vs.status == {"voice": "done", "draw": "done"} and vs.duration_ms == 1500 and vs.composed
    vd = versions.vscene_dir(pid, "v1", "01")
    assert (vd / "voice.wav").read_text() == "voice.wav" and (vd / "clip.mp4").exists()
    sd = store.scene_dir(pid, "01")
    assert (sd / "image.png").exists() and not (sd / "voice.wav").exists()
    assert p.final == "versions/v1/final.mp4"
    # idempotent
    assert versions.ensure(store.load(pid)) is False

def test_new_project_gets_v1_and_scene_entries():
    p = store.create_project("t", Settings(voice="Mai Anh"), "x")
    p.scenes = [Scene(id="01", text="a"), Scene(id="02", text="b")]
    store.save(p)
    q = store.load(pid := p.id)
    assert [v.id for v in q.versions] == ["v1"] and versions.get(q).voice == "Mai Anh"
    assert set(versions.get(q).scenes) == {"01", "02"}

def test_mirror_follows_active_version():
    p = store.load(store.create_project("t", Settings(), "x").id)
    p.scenes = [Scene(id="01", text="a")]
    versions.ensure(p)
    vs = versions.get(p).scenes["01"]
    vs.status = {"voice": "done", "draw": "running"}; vs.duration_ms = 900
    store.save(p)
    q = store.load(p.id)
    assert q.scenes[0].status["voice"] == "done" and q.scenes[0].status["draw"] == "running"
    assert q.scenes[0].duration_ms == 900

def test_invalidate_rules():
    p = store.load(store.create_project("t", Settings(), "x").id)
    p.scenes = [Scene(id="01", text="a", status={"image": "done", "voice": "pending", "draw": "pending"})]
    versions.ensure(p)
    v2 = versions.add_version(p, "Mai Anh")
    for v in p.versions:
        v.scenes["01"].status = {"voice": "done", "draw": "done"}; v.scenes["01"].composed = True
    versions.invalidate_scene(p, "01", "draw")
    assert all(v.scenes["01"].status == {"voice": "done", "draw": "pending"} for v in p.versions)
    assert not any(v.scenes["01"].composed for v in p.versions)
    for v in p.versions: v.scenes["01"].status = {"voice": "done", "draw": "done"}
    versions.invalidate_scene(p, "01", "voice", vid=v2.id)
    assert versions.get(p, "v1").scenes["01"].status == {"voice": "done", "draw": "done"}
    assert v2.scenes["01"].status == {"voice": "pending", "draw": "pending"}
    versions.invalidate_scene(p, "01", "image")
    assert p.scenes[0].status["image"] == "pending"
    assert versions.get(p, "v1").scenes["01"].status == {"voice": "done", "draw": "pending"}

def test_add_version_labels_and_activates():
    p = store.load(store.create_project("t", Settings(voice="Hải Đăng"), "x").id)
    p.scenes = [Scene(id="01", text="a")]; versions.ensure(p)
    v = versions.add_version(p, "Mai Anh")
    assert (v.id, v.label, p.active_version) == ("v2", "Bản 2 · Mai Anh", "v2")
    assert set(v.scenes) == {"01"}

def test_renumber_moves_version_dirs():
    p = store.load(store.create_project("t", Settings(), "x").id)
    p.scenes = [Scene(id="01", text="a"), Scene(id="02", text="b")]; versions.ensure(p)
    (versions.vscene_dir(p.id, "v1", "02") / "m.txt").write_text("B")
    versions.get(p).scenes["02"].duration_ms = 77
    versions.renumber(p, {"01", "02"}, {"01": "02"})
    assert (versions.vscene_dir(p.id, "v1", "01") / "m.txt").read_text() == "B"
    assert not (versions.vdir(p.id, "v1") / "scenes" / "02").exists()
    assert versions.get(p).scenes["01"].duration_ms == 77 and "02" not in versions.get(p).scenes

def test_narration_and_voice_helpers():
    s = Scene(id="01", text="API là gì.", narration="")
    assert versions.narration_of(s) == "API là gì."
    s.narration = "ây pi ai là gì."
    assert versions.narration_of(s) == "ây pi ai là gì."
    from studio.models import Version, VersionScene
    v = Version(id="v1", label="x", voice="Hải Đăng")
    assert versions.effective_voice(v, VersionScene()) == "Hải Đăng"
    assert versions.effective_voice(v, VersionScene(voice="Mai Anh")) == "Mai Anh"


def test_interrupted_migration_keeps_existing_destinations():
    pid = _legacy()
    pdir = store.project_dir(pid)
    (pdir / "final.mp4").unlink()
    vd = versions.vscene_dir(pid, "v1", "01")
    (vd / "voice.wav").write_text("NEW")
    (pdir / "versions" / "v1" / "final.mp4").write_text("vfinal")
    (store.scene_dir(pid, "01") / "voice.wav").write_text("OLD")
    p = store.load(pid)
    v = versions.get(p)
    assert v.final == "versions/v1/final.mp4" and v.scenes["01"].composed
    assert (vd / "voice.wav").read_text() == "NEW"

def test_load_does_not_write_on_mirror_only_difference():
    p = store.create_project("t", Settings(), "x")
    p.scenes = [Scene(id="01", text="a")]
    versions.ensure(p)
    store.save(p)
    f = store.project_dir(p.id) / "project.json"
    raw = json.loads(f.read_text())
    raw["scenes"][0]["status"]["voice"] = "done"
    f.write_text(json.dumps(raw))
    m = f.stat().st_mtime_ns
    q = store.load(p.id)
    assert f.stat().st_mtime_ns == m
    assert q.scenes[0].status["voice"] == "pending"

def test_sync_active_tolerates_partial_status():
    p = store.create_project("t", Settings(), "x")
    p.scenes = [Scene(id="01", text="a")]
    versions.ensure(p)
    versions.get(p).scenes["01"].status = {}
    versions.sync_active(p)
    assert p.scenes[0].status["voice"] == "pending" and p.scenes[0].status["draw"] == "pending"
