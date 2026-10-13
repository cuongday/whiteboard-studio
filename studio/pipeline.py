"""Pipeline steps.

NOTE: callers must not mutate the project (scenes/settings) while a job runs;
jobs hold a stale Project and save the whole thing after each step.
"""
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable
import cv2
from . import hand as hand_mod
from . import annotate as annotate_mod, compose, config, draw, llm, store, versions, voice

@dataclass
class Deps:
    segment: Callable = llm.segment_script
    gen_image: Callable = llm.generate_image
    synth: Callable = voice.synthesize
    annotate: Callable = annotate_mod.build_annotation
    draw: Callable = draw.render_clip
    render: Callable = compose.render_final
    preview: Callable = compose.make_preview
    progress: Callable[[str, float], None] = field(default=lambda msg, pct: None)
    cancel: threading.Event = field(default_factory=threading.Event)

class Cancelled(Exception):
    pass

def check_cancel(deps) -> None:
    if deps.cancel.is_set():
        raise Cancelled("Đã huỷ tác vụ")

IMAGE_WORKERS = int(os.environ.get("STUDIO_IMAGE_WORKERS", "4"))
# each whiteboard render is a single-threaded Python/OpenCV loop (~5-8 s per scene after
# the bounding-box optimisation in vendor/render_stream_whiteboard.py): ~1 core each
DRAW_WORKERS = int(os.environ.get("STUDIO_DRAW_WORKERS", str(max(1, min(8, (os.cpu_count() or 2) * 3 // 8)))))
_SAVE_LOCK = threading.Lock()   # steps run on worker threads but share one Project

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
    for v in p.versions:
        v.scenes = {}; v.final = None
    versions.ensure(p)
    p.stage = "scenes"
    store.save(p)

def _step(p, holder, sid, step, fn, deps, i, n, label):
    if deps.cancel.is_set():
        return False
    with _SAVE_LOCK:
        holder.status[step] = "running"; store.save(p)
    deps.progress(f"{label} cảnh {sid} ({i + 1}/{n})", i / n)
    try:
        fn()
        ok, err = True, None
    except Exception as e:  # noqa: BLE001 — isolate per-scene failures
        ok, err = False, f"{step}: {e}"
    with _SAVE_LOCK:
        if not ok and deps.cancel.is_set():
            holder.status[step] = "pending"; holder.error = None   # killed by a cancel, not a real failure
        else:
            holder.status[step] = "done" if ok else "error"; holder.error = err
        if hasattr(holder, "composed"):
            holder.composed = False
        store.save(p)
    return ok

def run_images(pid: str, deps: Deps, only: list[str] | None = None, model: str | None = None) -> None:
    p = store.load(pid)
    todo = [s for s in p.scenes if (only is not None and s.id in only) or (only is None and s.status["image"] != "done")]
    def one(i, s):
        out = store.scene_dir(pid, s.id) / "image.png"
        def work():
            used = model or p.settings.image_model
            tmp = out.with_name("image.new.png")
            deps.gen_image(s.image_prompt, p.settings.aspect, tmp, model=used)
            _fit(tmp, config.ASPECTS[p.settings.aspect])
            os.replace(tmp, out)
            s.image_model = used
            s.image_at = time.time()
            # only a scene that really got a new image must be redrawn in all versions
            with _SAVE_LOCK:
                versions.invalidate_scene(p, s.id, "image")
        _step(p, s, s.id, "image", work, deps, i, len(todo), "Vẽ ảnh")
    # Gemini calls are network-bound: generate several images at once
    with ThreadPoolExecutor(max_workers=max(1, IMAGE_WORKERS)) as ex:
        list(ex.map(one, range(len(todo)), todo))
    check_cancel(deps)
    if p.stage != "done":
        p.stage = "images"
    store.save(p)

def _build(p, v, deps, sids: list[str]) -> None:
    """Narrate (pending) and draw (pending) the given scenes of version v; preview after each draw."""
    pid = p.id
    by_id = {s.id: s for s in p.scenes}
    n = len(sids)
    order = {sid: i for i, sid in enumerate(sids)}

    def draw_scene(s):
        vs = v.scenes[s.id]; d = versions.vscene_dir(pid, v.id, s.id)
        def dr():
            if not (d / "narration.json").exists() and (d / "words.json").exists():
                # migrated pre-version scene: its words.json IS the narration timing; keep a copy
                # because words.json is about to be overwritten with subtitle timings
                shutil.copyfile(d / "words.json", d / "narration.json")
            narr_words = json.loads((d / "narration.json").read_text(encoding="utf-8"))
            spans = json.loads((d / "spans.json").read_text()) if (d / "spans.json").exists() else None
            words = voice.subtitle_words(s.text, versions.narration_of(s), narr_words, spans)
            (d / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            img = store.scene_dir(pid, s.id) / "image.png"
            ann = deps.annotate(img, s.elements, words, vs.duration_ms)
            deps.draw(img, ann, d / "clip.mp4", fps=config.FPS,
                      hand=hand_mod.hand_png(p.settings.pen_text, p.settings.pen_color))
            deps.preview(d / "clip.mp4", d / "voice.wav", d / "preview.mp4")
            vs.built_at = time.time()
        _step(p, vs, s.id, "draw", dr, deps, order[s.id], n, "Vẽ animation")

    def voice_scene(s):
        vs = v.scenes[s.id]; d = versions.vscene_dir(pid, v.id, s.id)
        def vo():
            deps.synth(versions.narration_of(s), versions.effective_voice(v, vs), d / "voice.wav")
            os.replace(d / "words.json", d / "narration.json")
            vs.duration_ms = voice.wav_duration_ms(d / "voice.wav")
        if not _step(p, vs, s.id, "voice", vo, deps, order[s.id], n, "Đọc"):
            return
        with _SAVE_LOCK:
            vs.status["draw"] = "pending"
        draws.append(draw_pool.submit(draw_scene, s))

    draws: list = []
    with ThreadPoolExecutor(max_workers=max(1, DRAW_WORKERS)) as draw_pool, \
         ThreadPoolExecutor(max_workers=max(1, voice.VOICE_WORKERS)) as voice_pool:
        voices = []
        for sid in sids:
            s = by_id[sid]; vs = v.scenes[sid]
            if s.status["image"] != "done":
                with _SAVE_LOCK:
                    vs.status["voice"] = "error"; vs.error = "Chưa có ảnh"; store.save(p)
                continue
            if vs.status["voice"] != "done":
                voices.append(voice_pool.submit(voice_scene, s))
            elif vs.status["draw"] != "done":
                draws.append(draw_pool.submit(draw_scene, s))
        for f in voices:
            f.result()
        voice_pool.shutdown(wait=True)
        for f in list(draws):
            f.result()

def _all_built(v) -> bool:
    return all(vs.status["voice"] == "done" and vs.status["draw"] == "done" for vs in v.scenes.values())

def _compose(p, v, deps) -> None:
    label = f"Đang ghép video ({'ffmpeg' if p.settings.composer == 'ffmpeg' else 'Remotion'})…"
    deps.progress(label, 0.9)
    try:
        deps.render(p, v.id, on_progress=lambda f: deps.progress(label, 0.9 + 0.1 * f))
    except Exception as e:  # noqa: BLE001
        p.stage = "done" if any(x.final for x in p.versions) else "images"
        p.job_error = f"Lỗi ghép video: {e}"; store.save(p)
        raise
    v.final = f"versions/{v.id}/final.mp4"
    for vs in v.scenes.values():
        vs.composed = True
    p.stage = "done"; store.save(p)

def _build_and_compose(p, v, deps) -> None:
    p.active_version = v.id; p.job_error = None
    if p.stage != "done":
        p.stage = "rendering"
    store.save(p)
    _build(p, v, deps, [s.id for s in p.scenes])
    if deps.cancel.is_set():
        p.stage = "done" if any(x.final for x in p.versions) else "images"; store.save(p)
        check_cancel(deps)
    if not _all_built(v):
        p.stage = "done" if any(x.final for x in p.versions) else "images"
        p.job_error = "Một số cảnh lỗi, hãy xem và thử lại"; store.save(p)
        raise RuntimeError(p.job_error)
    _compose(p, v, deps)

def run_render(pid: str, deps: Deps) -> None:
    p = store.load(pid)
    _build_and_compose(p, versions.get(p), deps)

def run_compose(pid: str, deps: Deps, version: str) -> None:
    p = store.load(pid)
    _build_and_compose(p, versions.get(p, version), deps)

def run_rebuild_scene(pid: str, deps: Deps, version: str, scene: str) -> None:
    p = store.load(pid)
    v = versions.get(p, version); vs = v.scenes[scene]
    p.active_version = v.id; p.job_error = None
    if vs.status["voice"] == "done" and vs.status["draw"] == "done":
        vs.status["draw"] = "pending"          # explicit rebuild = redraw
    store.save(p)
    _build(p, v, deps, [scene])
    check_cancel(deps)
    if vs.status["draw"] != "done":
        p.job_error = vs.error or "Dựng lại cảnh thất bại"; store.save(p)
        raise RuntimeError(p.job_error)

def run_new_version(pid: str, deps: Deps, voice: str) -> None:
    p = store.load(pid)
    v = versions.add_version(p, voice)
    _build_and_compose(p, v, deps)
