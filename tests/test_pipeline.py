import json
import cv2
import numpy as np
from studio import pipeline, store, versions
from studio.models import Settings, Scene, Element

used_models = []

def fake_segment(text, aspect, model=None):
    return [Scene(id="01", text="Giá tăng.", visual_description="x", elements=[Element(label="a", say="tăng")], image_prompt="p1"),
            Scene(id="02", text="Tiền giảm.", visual_description="y", elements=[Element(label="b", say="giảm")], image_prompt="p2")]

def fake_image(prompt, aspect, out, model=None):
    used_models.append(model)
    cv2.imwrite(str(out), np.full((100, 200, 3), 230, np.uint8)); return out

def fake_synth(text, voice, out_wav):
    import soundfile as sf
    sf.write(out_wav, np.zeros(24000), 24000)
    words = [{"text": w, "start_ms": 300 + i * 200, "end_ms": 450 + i * 200} for i, w in enumerate(text.split())]
    out_wav.with_name("words.json").write_text(json.dumps(words)); return words

calls = []
def fake_draw(image, ann, out, fps=30):
    calls.append(out.parent.name); out.write_bytes(b"mp4"); return out

def fake_render(p, vid, on_progress=None):
    d = versions.vdir(p.id, vid); d.mkdir(parents=True, exist_ok=True)
    f = d / "final.mp4"; f.write_bytes(b"final"); return f

def fake_preview(clip, wav, out):
    out.write_bytes(b"preview"); return out

def deps():
    return pipeline.Deps(segment=fake_segment, gen_image=fake_image, synth=fake_synth, draw=fake_draw,
                         render=fake_render, preview=fake_preview,
                         annotate=lambda img, els, words, dur: {"sceneDurationMs": dur, "elements": []})

def test_full_flow_and_resume():
    calls.clear()
    p = store.create_project("t", Settings(aspect="16:9"), "Giá tăng. Tiền giảm.")
    d = deps()
    pipeline.run_segment(p.id, d)
    assert store.load(p.id).stage == "scenes"
    pipeline.run_images(p.id, d)
    q = store.load(p.id)
    img = cv2.imread(str(store.scene_dir(p.id, "01") / "image.png"))
    assert img.shape[:2] == (1080, 1920) and q.stage == "images"
    pipeline.run_render(p.id, d)
    q = store.load(p.id)
    assert q.stage == "done" and q.final == "versions/v1/final.mp4" and q.scenes[0].duration_ms == 1000
    assert sorted(calls) == ["01", "02"]
    # edit scene 02 text -> only 02 re-voiced/redrawn
    q.scenes[1].text = "Tiền giảm mạnh."; versions.invalidate_scene(q, "02", "voice"); store.save(q)
    calls.clear(); pipeline.run_render(p.id, d)
    assert calls == ["02"]

def test_scene_error_isolated():
    p = store.create_project("t", Settings(), "x")
    d = deps()
    pipeline.run_segment(p.id, d)
    def bad_image(prompt, aspect, out, model=None):
        if prompt == "p2": raise RuntimeError("boom")
        return fake_image(prompt, aspect, out, model)
    d.gen_image = bad_image
    pipeline.run_images(p.id, d)
    q = store.load(p.id)
    assert q.scenes[0].status["image"] == "done"
    assert q.scenes[1].status["image"] == "error" and "boom" in q.scenes[1].error

def test_render_failure_resets_stage():
    import pytest
    p = store.create_project("t", Settings(aspect="16:9"), "x")
    d = deps()
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d)
    def bad_render(p, vid, on_progress=None): raise RuntimeError("ffmpeg died")
    d.render = bad_render
    with pytest.raises(RuntimeError):
        pipeline.run_render(p.id, d)
    q = store.load(p.id)
    assert q.stage == "images" and "Lỗi ghép video" in q.job_error

def test_render_draws_in_parallel(monkeypatch):
    import threading, time as _t
    monkeypatch.setattr(pipeline, "DRAW_WORKERS", 2)
    live, peak, lock = [0], [0], threading.Lock()
    def slow_draw(image, ann, out, fps=30):
        with lock:
            live[0] += 1; peak[0] = max(peak[0], live[0])
        _t.sleep(0.3)
        with lock:
            live[0] -= 1
        out.write_bytes(b"mp4"); return out
    p = store.create_project("t", Settings(), "x")
    d = deps(); d.draw = slow_draw
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d); pipeline.run_render(p.id, d)
    assert store.load(p.id).stage == "done"
    assert peak[0] == 2

def test_models_flow_through():
    seen = {}
    def seg(text, aspect, model=None):
        seen["text"] = model; return fake_segment(text, aspect)
    p = store.create_project("t", Settings(text_model="gemini-3.8-flash", image_model="gemini-3-pro-image"), "x")
    d = deps(); d.segment = seg
    used_models.clear()
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d)
    assert seen["text"] == "gemini-3.8-flash"
    assert used_models == ["gemini-3-pro-image", "gemini-3-pro-image"]
    used_models.clear()
    pipeline.run_images(p.id, d, only=["02"], model="gemini-3.1-flash-lite-image")
    q = store.load(p.id)
    assert used_models == ["gemini-3.1-flash-lite-image"]
    assert (q.scenes[0].image_model, q.scenes[1].image_model) == ("gemini-3-pro-image", "gemini-3.1-flash-lite-image")

def test_render_voices_in_parallel(monkeypatch):
    import threading, time as _t
    from studio import voice as voice_mod
    monkeypatch.setattr(voice_mod, "VOICE_WORKERS", 2)
    live, peak, lock = [0], [0], threading.Lock()
    def slow_synth(text, v, out_wav):
        with lock:
            live[0] += 1; peak[0] = max(peak[0], live[0])
        _t.sleep(0.3)
        with lock:
            live[0] -= 1
        return fake_synth(text, v, out_wav)
    p = store.create_project("t", Settings(), "x")
    d = deps(); d.synth = slow_synth
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d); pipeline.run_render(p.id, d)
    q = store.load(p.id)
    assert q.stage == "done" and all(s.status["draw"] == "done" for s in q.scenes)
    assert peak[0] == 2

synth_calls = []
def recording_synth(text, voice, out_wav):
    synth_calls.append((out_wav.parent.parent.parent.name, out_wav.parent.name, text, voice))
    return fake_synth(text, voice, out_wav)

def _done_project():
    p = store.create_project("t", Settings(voice="Hải Đăng"), "x")
    d = deps(); d.synth = recording_synth
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d); pipeline.run_render(p.id, d)
    return p.id, d

def test_render_writes_version_files():
    pid, _ = _done_project()
    vd = versions.vscene_dir(pid, "v1", "01")
    for f in ("voice.wav", "narration.json", "words.json", "clip.mp4", "preview.mp4"):
        assert (vd / f).exists(), f
    q = store.load(pid)
    assert all(vs.composed for vs in versions.get(q).scenes.values())

def test_narration_differs_from_subtitle():
    pid, d = _done_project()
    q = store.load(pid); q.scenes[0].narration = "Gia tang."; versions.invalidate_scene(q, "01", "voice"); store.save(q)
    synth_calls.clear(); calls.clear()
    pipeline.run_rebuild_scene(pid, d, version="v1", scene="01")
    assert synth_calls == [("v1", "01", "Gia tang.", "Hải Đăng")] and calls == ["01"]
    words = json.loads((versions.vscene_dir(pid, "v1", "01") / "words.json").read_text())
    assert [w["text"] for w in words] == ["Giá", "tăng."]          # captions keep the subtitle
    q = store.load(pid)
    assert versions.get(q).scenes["01"].composed is False and q.stage == "done"

def test_rebuild_without_changes_redraws_only():
    pid, d = _done_project()
    synth_calls.clear(); calls.clear()
    pipeline.run_rebuild_scene(pid, d, version="v1", scene="02")
    assert synth_calls == [] and calls == ["02"]

def test_compose_rebuilds_only_pending_then_composes():
    pid, d = _done_project()
    q = store.load(pid); versions.invalidate_scene(q, "02", "draw"); store.save(q)
    calls.clear()
    pipeline.run_compose(pid, d, version="v1")
    q = store.load(pid)
    assert calls == ["02"] and all(vs.composed for vs in versions.get(q).scenes.values())
    assert q.final == "versions/v1/final.mp4" and q.stage == "done"

def test_new_version_keeps_old_files():
    pid, d = _done_project()
    v1_final = versions.vdir(pid, "v1") / "final.mp4"; v1_final.write_bytes(b"OLD")
    synth_calls.clear()
    pipeline.run_new_version(pid, d, voice="Mai Anh")
    q = store.load(pid)
    assert [v.id for v in q.versions] == ["v1", "v2"] and q.active_version == "v2"
    assert {c[3] for c in synth_calls} == {"Mai Anh"} and {c[0] for c in synth_calls} == {"v2"}
    assert v1_final.read_bytes() == b"OLD" and q.final == "versions/v2/final.mp4"

def test_per_scene_voice_override():
    pid, d = _done_project()
    q = store.load(pid)
    versions.get(q).scenes["02"].voice = "Mai Anh"; versions.invalidate_scene(q, "02", "voice", vid="v1"); store.save(q)
    synth_calls.clear()
    pipeline.run_rebuild_scene(pid, d, version="v1", scene="02")
    assert synth_calls[0][3] == "Mai Anh"
