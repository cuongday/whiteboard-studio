import asyncio
import json
import re
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, store, versions, hand as hand_mod, voice as voice_mod
from .checks import run_checks
from .ingest import extract_text
from .jobs import JOBS, job_alive_elsewhere
from .llm import build_image_prompt
from .models import STEPS, Element, Scene, Settings

def reset_stale() -> None:
    """Reset state left over from a crash: running steps -> pending, rendering -> images."""
    if not config.PROJECTS_DIR.exists():
        return
    for d in config.PROJECTS_DIR.iterdir():
        try:
            if not (d / "project.json").exists() or job_alive_elsewhere(d):
                continue
            p = store.load(d.name)
            changed = False
            for s in p.scenes:
                for k, v in list(s.status.items()):
                    if v == "running":
                        s.status[k] = "pending"; changed = True
            for v in p.versions:
                for vs in v.scenes.values():
                    for k, val in list(vs.status.items()):
                        if val == "running":
                            vs.status[k] = "pending"; changed = True
            if p.stage == "rendering":
                # a project that already has a playable video stays on the result screen
                p.stage = "done" if any(v.final for v in p.versions) else "images"; changed = True
            if changed:
                store.save(p)
        except Exception:  # noqa: BLE001
            continue

@asynccontextmanager
async def lifespan(_app):
    reset_stale()
    yield

app = FastAPI(title="Whiteboard Studio", lifespan=lifespan)

_PID_RE = re.compile(r"^[a-f0-9]{10}$")

def _busy_check():
    if JOBS.busy:
        raise HTTPException(409, "Đang có tác vụ khác chạy")

def _get(pid):
    if not _PID_RE.match(pid):
        raise HTTPException(404, "Không tìm thấy dự án")
    try:
        return store.load(pid)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy dự án")

def _submit(pid, kind, **kw):
    if not JOBS.submit(pid, kind, **kw):
        raise HTTPException(409, "Đang có tác vụ khác chạy")

@app.get("/api/models")
def models():
    pack = lambda ms: [{"id": m, "label": label} for m, label in ms]  # noqa: E731
    return {"text": pack(config.TEXT_MODELS), "image": pack(config.IMAGE_MODELS),
            "default_text": config.TEXT_MODEL, "default_image": config.IMAGE_MODEL}

def _check_model(model: str | None, allowed) -> None:
    if model and model not in {m for m, _ in allowed}:
        raise HTTPException(400, f"Model không hỗ trợ: {model}")

def _pen(text, color) -> dict:
    t, c = hand_mod.normalize(text, color)
    return {"pen_text": t, "pen_color": c}

@app.get("/api/hand")
def hand_preview(text: str = "", color: str = ""):
    """PNG of the drawing hand with the given marker text (for the settings preview)."""
    try:
        return FileResponse(hand_mod.hand_png(text, color), media_type="image/png")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Không tạo được ảnh bút: {e}")

@app.get("/api/voices")
async def voices():
    from .voice import list_voices
    return await asyncio.to_thread(list_voices)

@app.get("/api/health")
def health():
    return {"checks": run_checks()}

@app.get("/api/jobs")
def jobs_state():
    busy = JOBS.busy
    return {"busy": busy, "pid": JOBS.pid if busy else None, "kind": JOBS.kind if busy else None,
            "started_at": JOBS.started_at if busy else None,
            "progress": JOBS.last_progress if busy else None}

@app.get("/api/projects")
def projects():
    return [p.model_dump() for p in store.list_projects()]

@app.get("/api/projects/{pid}")
def project(pid: str):
    return _get(pid).model_dump()

@app.post("/api/projects")
async def create(title: str = Form(""), text: str = Form(""), aspect: str = Form("16:9"),
                 voice: str = Form("Hải Đăng"), captions: bool = Form(True), music: bool = Form(False),
                 text_model: str = Form(""), image_model: str = Form(""),
                 pen_text: str = Form(""), pen_color: str = Form(""),
                 file: UploadFile | None = File(None), music_file: UploadFile | None = File(None)):
    _busy_check()
    _check_model(text_model, config.TEXT_MODELS); _check_model(image_model, config.IMAGE_MODELS)
    try:
        source = extract_text(file.filename, await file.read()) if file and file.filename else text.strip()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Không đọc được file: {e}")
    if not source:
        raise HTTPException(400, "Cần nhập kịch bản hoặc tải file")
    p = store.create_project(title, Settings(aspect=aspect, voice=voice, captions=captions, music=music,
                                             text_model=text_model or config.TEXT_MODEL,
                                             image_model=image_model or config.IMAGE_MODEL,
                                             **_pen(pen_text, pen_color)), source)
    if music_file and music_file.filename:
        up = store.project_dir(p.id) / "uploads"; up.mkdir(parents=True, exist_ok=True)
        ext = Path(music_file.filename).suffix.lower()
        if ext not in {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}:
            shutil.rmtree(store.project_dir(p.id), ignore_errors=True)
            raise HTTPException(400, "Định dạng nhạc không hỗ trợ")
        name = "music" + ext
        (up / name).write_bytes(await music_file.read())
        p.settings.music_file = f"uploads/{name}"; store.save(p)
    _submit(p.id, "segment")
    return p.model_dump()

@app.put("/api/projects/{pid}/scenes")
def update_scenes(pid: str, scenes: list[Scene]):
    _busy_check()
    p = _get(pid)
    if p.stage not in ("scenes", "images", "done"):
        raise HTTPException(409, "Không thể sửa cảnh lúc này")
    old = {s.id: s for s in p.scenes}
    used: set[str] = set()
    new, moves, inval = [], {}, []
    for i, inc in enumerate(scenes, 1):
        nid = f"{i:02d}"
        prev = old.get(inc.id) if inc.id not in used else None
        if prev is None:
            s = inc.model_copy(update={"id": nid, "status": {k: "pending" for k in STEPS},
                                       "error": None, "duration_ms": None})
            s.image_prompt = build_image_prompt(s)
        else:
            used.add(inc.id)
            s = inc.model_copy(update={"id": nid, "status": dict(prev.status), "error": prev.error,
                                       "duration_ms": prev.duration_ms})
            if prev.visual_description != s.visual_description:
                s.image_prompt = build_image_prompt(s); inval.append((nid, "image"))
            elif prev.elements != s.elements:
                s.image_prompt = inc.image_prompt or prev.image_prompt; inval.append((nid, "draw"))
            if versions.narration_of(prev) != versions.narration_of(s):
                inval.append((nid, "voice"))
            elif prev.text != s.text:
                inval.append((nid, "draw"))
            moves[nid] = prev.id
        new.append(s)
    versions.renumber(p, set(old), moves)
    p.scenes = new
    versions.ensure(p)
    for nid, step in inval:
        versions.invalidate_scene(p, nid, step)
    structural = set(moves) != set(old) or any(nid != oid for nid, oid in moves.items()) or len(new) != len(old)
    if p.stage == "done" and (inval or structural):
        p.stage = "images"
    store.save(p)
    return p.model_dump()

@app.put("/api/projects/{pid}/settings")
def update_settings(pid: str, settings: Settings):
    _busy_check()
    p = _get(pid)
    _check_model(settings.text_model, config.TEXT_MODELS); _check_model(settings.image_model, config.IMAGE_MODELS)
    invalidated = False
    if settings.voice != p.settings.voice:
        v = versions.get(p)
        v.voice = settings.voice
        v.label = versions.label_for(int(v.id[1:]), settings.voice)
        for s_ in p.scenes:
            vs_ = v.scenes.get(s_.id)
            if vs_ is not None and vs_.status["voice"] == "done":
                versions.invalidate_scene(p, s_.id, "voice", vid=v.id); invalidated = True
        v.final = None
    if settings.aspect != p.settings.aspect:
        for s_ in p.scenes:
            versions.invalidate_scene(p, s_.id, "image")
        for v in p.versions:
            v.final = None
        invalidated = True
    if invalidated and p.stage == "done":
        p.stage = "images"
    pen = _pen(settings.pen_text, settings.pen_color)
    if (pen["pen_text"], pen["pen_color"]) != (p.settings.pen_text, p.settings.pen_color):
        # the hand is drawn into every clip: redraw everything (voice is kept)
        for s_ in p.scenes:
            versions.invalidate_scene(p, s_.id, "draw")
        if p.stage == "done":
            p.stage = "images"
    settings.pen_text, settings.pen_color = pen["pen_text"], pen["pen_color"]
    settings.music_file = p.settings.music_file
    p.settings = settings; store.save(p)
    return p.model_dump()

class ImagesBatch(BaseModel):
    image_model: str | None = None   # None = project default
    all: bool = False                # True = redraw every scene, else only missing/failed ones

@app.post("/api/projects/{pid}/approve/scenes")
def approve_scenes(pid: str, body: ImagesBatch | None = None):
    p = _get(pid)
    if p.stage not in ("scenes", "images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    body = body or ImagesBatch()
    _check_model(body.image_model, config.IMAGE_MODELS)
    if p.stage == "done" and not body.all and all(s.status["image"] == "done" for s in p.scenes):
        raise HTTPException(409, "Không có ảnh nào lỗi hoặc còn thiếu")
    kw = {"model": body.image_model} if body.image_model else {}
    if body.all:
        kw["only"] = [s.id for s in p.scenes]
    _submit(pid, "images", **kw); return {"ok": True}

class Resegment(BaseModel):
    text_model: str | None = None

@app.post("/api/projects/{pid}/segment")
def resegment(pid: str, body: Resegment | None = None):
    p = _get(pid)
    if p.stage not in ("input", "scenes"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _busy_check()
    if body and body.text_model:
        _check_model(body.text_model, config.TEXT_MODELS); p.settings.text_model = body.text_model
    p.job_error = None; store.save(p)
    _submit(pid, "segment"); return {"ok": True}

class Regen(BaseModel):
    image_prompt: str | None = None
    image_model: str | None = None

@app.post("/api/projects/{pid}/scenes/{sid}/regenerate")
def regenerate(pid: str, sid: str, body: Regen):
    p = _get(pid)
    _busy_check()
    s = next((x for x in p.scenes if x.id == sid), None)
    if not s: raise HTTPException(404, "Không có cảnh")
    _check_model(body.image_model, config.IMAGE_MODELS)
    if body.image_prompt: s.image_prompt = body.image_prompt
    store.save(p); _submit(pid, "images", only=[sid], model=body.image_model); return {"ok": True}

@app.post("/api/projects/{pid}/render")
def render(pid: str):
    p = _get(pid)
    if p.stage not in ("images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _submit(pid, "render"); return {"ok": True}

def _scene(p, sid):
    s = next((x for x in p.scenes if x.id == sid), None)
    if not s:
        raise HTTPException(404, "Không có cảnh")
    return s

def _version(p, vid):
    try:
        return versions.get(p, vid)
    except KeyError:
        raise HTTPException(404, "Không có phiên bản")

class SceneEdit(BaseModel):
    text: str | None = None
    narration: str | None = None
    elements: list[Element] | None = None

@app.put("/api/projects/{pid}/scenes/{sid}")
def edit_scene(pid: str, sid: str, body: SceneEdit):
    _busy_check()
    p = _get(pid); s = _scene(p, sid)
    before_narr, before_text, before_els = versions.narration_of(s), s.text, list(s.elements)
    if body.text is not None:
        s.text = body.text.strip()
    if body.narration is not None:
        s.narration = body.narration.strip()
    if body.elements is not None:
        s.elements = body.elements
    if versions.narration_of(s) != before_narr:
        versions.invalidate_scene(p, sid, "voice")
    elif s.text != before_text or s.elements != before_els:
        versions.invalidate_scene(p, sid, "draw")
    store.save(p)
    return p.model_dump()

class VoiceOverride(BaseModel):
    voice: str | None = None

@app.put("/api/projects/{pid}/versions/{vid}/scenes/{sid}")
def set_scene_voice(pid: str, vid: str, sid: str, body: VoiceOverride):
    _busy_check()
    p = _get(pid); _scene(p, sid); v = _version(p, vid)
    new = (body.voice or "").strip() or None
    if new == v.voice:
        new = None
    if new != v.scenes[sid].voice:
        v.scenes[sid].voice = new
        versions.invalidate_scene(p, sid, "voice", vid=vid)
    store.save(p)
    return p.model_dump()

@app.post("/api/projects/{pid}/versions/{vid}/scenes/{sid}/rebuild")
def rebuild_scene(pid: str, vid: str, sid: str):
    p = _get(pid); _scene(p, sid); _version(p, vid)
    if p.stage not in ("images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _submit(pid, "rebuild_scene", version=vid, scene=sid); return {"ok": True}

@app.post("/api/projects/{pid}/versions/{vid}/compose")
def compose_version(pid: str, vid: str):
    p = _get(pid); _version(p, vid)
    if p.stage not in ("images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _submit(pid, "compose", version=vid); return {"ok": True}

class NewVersion(BaseModel):
    voice: str

@app.post("/api/projects/{pid}/versions")
def new_version(pid: str, body: NewVersion):
    p = _get(pid)
    if p.stage not in ("images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    if not body.voice.strip():
        raise HTTPException(400, "Cần chọn giọng")
    _submit(pid, "new_version", voice=body.voice.strip()); return {"ok": True}

class ActiveVersion(BaseModel):
    id: str

@app.put("/api/projects/{pid}/active_version")
def set_active_version(pid: str, body: ActiveVersion):
    _busy_check()
    p = _get(pid); _version(p, body.id)
    p.active_version = body.id; store.save(p)
    return p.model_dump()

class Listen(BaseModel):
    narration: str
    voice: str

@app.post("/api/projects/{pid}/scenes/{sid}/listen")
def listen(pid: str, sid: str, body: Listen):
    p = _get(pid); _scene(p, sid)
    if not body.narration.strip():
        raise HTTPException(400, "Lời đọc trống")
    out = store.project_dir(pid) / "tmp" / f"listen-{sid}.wav"
    try:
        voice_mod.synthesize(body.narration.strip(), body.voice, out, timeout=60)
    except TimeoutError:
        raise HTTPException(503, "Đang bận, thử lại")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Lỗi đọc thử: {e}")
    return {"url": f"/api/projects/{pid}/files/tmp/listen-{sid}.wav?v={int(time.time() * 1000)}"}

@app.get("/api/projects/{pid}/events")
async def events(pid: str):
    q = JOBS.subscribe()
    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.to_thread(q.get, True, 15)
                except Exception:  # queue.Empty -> keepalive
                    yield ": ping\n\n"; continue
                if ev["pid"] == pid:
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            JOBS.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/projects/{pid}/files/{path:path}")
def files(pid: str, path: str):
    _get(pid)
    base = store.project_dir(pid).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "Không có file")
    return FileResponse(f)

_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
