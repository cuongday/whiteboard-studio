"""Pipeline steps.

NOTE: callers must not mutate the project (scenes/settings) while a job runs;
jobs hold a stale Project and save the whole thing after each step.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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

IMAGE_WORKERS = int(os.environ.get("STUDIO_IMAGE_WORKERS", "4"))
# each whiteboard render is a single-threaded Python/OpenCV loop (~5-8 s per scene after
# the bounding-box optimisation in vendor/render_stream_whiteboard.py): ~1 core each
DRAW_WORKERS = int(os.environ.get("STUDIO_DRAW_WORKERS", str(max(1, min(8, (os.cpu_count() or 2) * 3 // 8)))))
_SAVE_LOCK = threading.Lock()   # steps run on worker threads but share one Project

def invalidate(scene: Scene, from_step: str) -> None:
    for s in STEPS[STEPS.index(from_step):]:
        scene.status[s] = "pending"
    scene.error = None

def _fit(path, size):
    w, h = size
    img = cv2.imread(str(path))
    ih, iw = img.shape[:2]
    scale = max(w / iw, h / ih)
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    img = cv2.resize(img, (round(iw * scale), round(ih * scale)), interpolation=interp)
    y, x = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
    cv2.imwrite(str(path), img[y:y + h, x:x + w])

def run_segment(pid: str, deps: Deps) -> None:
    p = store.load(pid)
    deps.progress("Đang chia cảnh…", 0.1)
    p.scenes = deps.segment(p.source_text, p.settings.aspect, model=p.settings.text_model)
    p.final = None
    p.stage = "scenes"
    store.save(p)

def _step(p, scene, step, fn, deps, i, n, label):
    with _SAVE_LOCK:
        scene.status[step] = "running"; store.save(p)
    deps.progress(f"{label} cảnh {scene.id} ({i + 1}/{n})", i / n)
    try:
        fn()
        ok, err = True, None
    except Exception as e:  # noqa: BLE001 — isolate per-scene failures
        ok, err = False, f"{step}: {e}"
    with _SAVE_LOCK:
        scene.status[step] = "done" if ok else "error"; scene.error = err
        store.save(p)
    return ok

def run_images(pid: str, deps: Deps, only: list[str] | None = None, model: str | None = None) -> None:
    p = store.load(pid)
    todo = [s for s in p.scenes if (only is not None and s.id in only) or (only is None and s.status["image"] != "done")]
    if only is not None:
        p.final = None
    def one(i, s):
        out = store.scene_dir(pid, s.id) / "image.png"
        def work():
            used = model or p.settings.image_model
            deps.gen_image(s.image_prompt, p.settings.aspect, out, model=used)
            s.image_model = used
            _fit(out, config.ASPECTS[p.settings.aspect])
        _step(p, s, "image", work, deps, i, len(todo), "Vẽ ảnh")
    if only is not None:
        for s in todo:
            invalidate(s, "image")
    # Gemini calls are network-bound: generate several images at once
    with ThreadPoolExecutor(max_workers=max(1, IMAGE_WORKERS)) as ex:
        list(ex.map(one, range(len(todo)), todo))
    p.stage = "images"
    store.save(p)

def run_render(pid: str, deps: Deps) -> None:
    p = store.load(pid)
    p.stage = "rendering"; p.job_error = None; p.final = None; store.save(p)
    n = len(p.scenes)

    def draw_scene(i, s, d):
        def dr():
            words = json.loads((d / "words.json").read_text(encoding="utf-8"))
            ann = deps.annotate(d / "image.png", s.elements, words, s.duration_ms)
            deps.draw(d / "image.png", ann, d / "clip.mp4", fps=config.FPS)
        _step(p, s, "draw", dr, deps, i, n, "Vẽ animation")

    def voice_scene(i, s, d):
        def v():
            deps.synth(s.text, p.settings.voice, d / "voice.wav")
            s.duration_ms = voice.wav_duration_ms(d / "voice.wav")
        if not _step(p, s, "voice", v, deps, i, n, "Đọc"):
            return
        with _SAVE_LOCK:
            s.status["draw"] = "pending"
        draws.append(draw_pool.submit(draw_scene, i, s, d))

    # Narration (several VieNeu instances) and whiteboard drawing run in two pools; each
    # scene's drawing starts as soon as its own narration is ready.
    draws: list = []
    with ThreadPoolExecutor(max_workers=max(1, DRAW_WORKERS)) as draw_pool, \
         ThreadPoolExecutor(max_workers=max(1, voice.VOICE_WORKERS)) as voice_pool:
        voices = []
        for i, s in enumerate(p.scenes):
            d = store.scene_dir(pid, s.id)
            if s.status["image"] != "done":
                with _SAVE_LOCK:
                    s.status["voice"] = "error"; s.error = "Chưa có ảnh"; store.save(p)
                continue
            if s.status["voice"] != "done":
                voices.append(voice_pool.submit(voice_scene, i, s, d))
            elif s.status["draw"] != "done":
                draws.append(draw_pool.submit(draw_scene, i, s, d))
        for f in voices:
            f.result()
        voice_pool.shutdown(wait=True)
        for f in list(draws):
            f.result()
    if any(s.status["draw"] != "done" or s.status["voice"] != "done" for s in p.scenes):
        p.stage = "images"; p.job_error = "Một số cảnh lỗi, hãy xem và thử lại"; store.save(p)
        raise RuntimeError(p.job_error)
    deps.progress("Đang ghép video…", 0.9)
    try:
        deps.render(p, on_progress=lambda f: deps.progress("Đang ghép video…", 0.9 + 0.1 * f))
    except Exception as e:  # noqa: BLE001
        p.stage = "images"; p.job_error = f"Lỗi ghép video: {e}"; store.save(p)
        raise
    p.final = "final.mp4"; p.stage = "done"; store.save(p)
