from dataclasses import dataclass, field
from typing import Callable
import cv2
from . import annotate as annotate_mod, compose, config, draw, llm, store, voice
from .models import STEPS, Scene

@dataclass
class Deps:
    segment: Callable = llm.segment_script
    gen_image: Callable = llm.generate_image
    synth: Callable = voice.synthesize
    annotate: Callable = annotate_mod.build_annotation
    draw: Callable = draw.render_clip
    render: Callable = compose.render_final
    progress: Callable[[str, float], None] = field(default=lambda msg, pct: None)

def invalidate(scene: Scene, from_step: str) -> None:
    for s in STEPS[STEPS.index(from_step):]:
        scene.status[s] = "pending"
    scene.error = None

def _fit(path, size):
    w, h = size
    img = cv2.imread(str(path))
    ih, iw = img.shape[:2]
    scale = max(w / iw, h / ih)
    img = cv2.resize(img, (round(iw * scale), round(ih * scale)), interpolation=cv2.INTER_AREA)
    y, x = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
    cv2.imwrite(str(path), img[y:y + h, x:x + w])

def run_segment(pid: str, deps: Deps) -> None:
    p = store.load(pid)
    deps.progress("Đang chia cảnh…", 0.1)
    p.scenes = deps.segment(p.source_text, p.settings.aspect)
    p.stage = "scenes"
    store.save(p)

def _step(p, scene, step, fn, deps, i, n, label):
    scene.status[step] = "running"; store.save(p)
    deps.progress(f"{label} cảnh {scene.id} ({i + 1}/{n})", i / n)
    try:
        fn()
        scene.status[step] = "done"; scene.error = None
    except Exception as e:  # noqa: BLE001 — isolate per-scene failures
        scene.status[step] = "error"; scene.error = f"{step}: {e}"
    store.save(p)
    return scene.status[step] == "done"

def run_images(pid: str, deps: Deps, only: list[str] | None = None) -> None:
    p = store.load(pid)
    todo = [s for s in p.scenes if (only and s.id in only) or (not only and s.status["image"] != "done")]
    for i, s in enumerate(todo):
        if only:
            invalidate(s, "image")
        out = store.scene_dir(pid, s.id) / "image.png"
        def work(s=s, out=out):
            deps.gen_image(s.image_prompt, p.settings.aspect, out)
            _fit(out, config.ASPECTS[p.settings.aspect])
        _step(p, s, "image", work, deps, i, len(todo), "Vẽ ảnh")
    p.stage = "images"
    store.save(p)

def run_render(pid: str, deps: Deps) -> None:
    p = store.load(pid)
    p.stage = "rendering"; p.job_error = None; store.save(p)
    n = len(p.scenes)
    for i, s in enumerate(p.scenes):
        d = store.scene_dir(pid, s.id)
        if s.status["image"] != "done":
            s.status["voice"] = "error"; s.error = "Chưa có ảnh"; store.save(p); continue
        if s.status["voice"] != "done":
            def v(s=s, d=d):
                deps.synth(s.text, p.settings.voice, d / "voice.wav")
                s.duration_ms = voice.wav_duration_ms(d / "voice.wav")
            if not _step(p, s, "voice", v, deps, i, n, "Đọc"):
                continue
            s.status["draw"] = "pending"
        if s.status["draw"] != "done":
            def dr(s=s, d=d):
                import json
                words = json.loads((d / "words.json").read_text(encoding="utf-8"))
                ann = deps.annotate(d / "image.png", s.elements, words, s.duration_ms)
                deps.draw(d / "image.png", ann, d / "clip.mp4", fps=config.FPS)
            _step(p, s, "draw", dr, deps, i, n, "Vẽ animation")
    if any(s.status["draw"] != "done" for s in p.scenes):
        p.stage = "images"; p.job_error = "Một số cảnh lỗi, hãy xem và thử lại"; store.save(p)
        raise RuntimeError(p.job_error)
    deps.progress("Đang ghép video…", 0.9)
    deps.render(p, on_progress=lambda f: deps.progress("Đang ghép video…", 0.9 + 0.1 * f))
    p.final = "final.mp4"; p.stage = "done"; store.save(p)
