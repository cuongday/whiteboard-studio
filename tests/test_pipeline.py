import json
import cv2
import numpy as np
from studio import pipeline, store
from studio.models import Settings, Scene, Element

def fake_segment(text, aspect):
    return [Scene(id="01", text="Giá tăng.", visual_description="x", elements=[Element(label="a", say="tăng")], image_prompt="p1"),
            Scene(id="02", text="Tiền giảm.", visual_description="y", elements=[Element(label="b", say="giảm")], image_prompt="p2")]

def fake_image(prompt, aspect, out):
    cv2.imwrite(str(out), np.full((100, 200, 3), 230, np.uint8)); return out

def fake_synth(text, voice, out_wav):
    import soundfile as sf
    sf.write(out_wav, np.zeros(24000), 24000)
    words = [{"text": w, "start_ms": 300 + i * 200, "end_ms": 450 + i * 200} for i, w in enumerate(text.split())]
    out_wav.with_name("words.json").write_text(json.dumps(words)); return words

calls = []
def fake_draw(image, ann, out, fps=30):
    calls.append(out.parent.name); out.write_bytes(b"mp4"); return out

def fake_render(p, on_progress=None):
    f = store.project_dir(p.id) / "final.mp4"; f.write_bytes(b"final"); return f

def deps():
    return pipeline.Deps(segment=fake_segment, gen_image=fake_image, synth=fake_synth, draw=fake_draw,
                         render=fake_render, annotate=lambda img, els, words, dur: {"sceneDurationMs": dur, "elements": []})

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
    assert q.stage == "done" and q.final == "final.mp4" and q.scenes[0].duration_ms == 1000
    assert calls == ["01", "02"]
    # edit scene 02 text -> only 02 re-voiced/redrawn
    q.scenes[1].text = "Tiền giảm mạnh."; pipeline.invalidate(q.scenes[1], "voice"); store.save(q)
    calls.clear(); pipeline.run_render(p.id, d)
    assert calls == ["02"]

def test_scene_error_isolated():
    p = store.create_project("t", Settings(), "x")
    d = deps()
    pipeline.run_segment(p.id, d)
    def bad_image(prompt, aspect, out):
        if prompt == "p2": raise RuntimeError("boom")
        return fake_image(prompt, aspect, out)
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
    def bad_render(p, on_progress=None): raise RuntimeError("ffmpeg died")
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
