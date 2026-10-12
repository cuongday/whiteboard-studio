import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, store
from .checks import run_checks
from .ingest import extract_text
from .jobs import JOBS
from .llm import build_image_prompt
from .models import STEPS, Scene, Settings
from .pipeline import invalidate

def reset_stale() -> None:
    """Reset state left over from a crash: running steps -> pending, rendering -> images."""
    if not config.PROJECTS_DIR.exists():
        return
    for d in config.PROJECTS_DIR.iterdir():
        try:
            if not (d / "project.json").exists():
                continue
            p = store.load(d.name)
            changed = False
            for s in p.scenes:
                for k, v in list(s.status.items()):
                    if v == "running":
                        s.status[k] = "pending"; changed = True
            if p.stage == "rendering":
                p.stage = "images"; changed = True
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
    return {"busy": busy, "pid": JOBS.pid if busy else None}

@app.get("/api/projects")
def projects():
    return [p.model_dump() for p in store.list_projects()]

@app.get("/api/projects/{pid}")
def project(pid: str):
    return _get(pid).model_dump()

@app.post("/api/projects")
async def create(title: str = Form(""), text: str = Form(""), aspect: str = Form("16:9"),
                 voice: str = Form("Hải Đăng"), captions: bool = Form(True), music: bool = Form(False),
                 file: UploadFile | None = File(None), music_file: UploadFile | None = File(None)):
    _busy_check()
    try:
        source = extract_text(file.filename, await file.read()) if file and file.filename else text.strip()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Không đọc được file: {e}")
    if not source:
        raise HTTPException(400, "Cần nhập kịch bản hoặc tải file")
    p = store.create_project(title, Settings(aspect=aspect, voice=voice, captions=captions, music=music), source)
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
    new, moves = [], {}
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
                s.image_prompt = build_image_prompt(s); invalidate(s, "image")
            elif prev.elements != s.elements:
                s.image_prompt = prev.image_prompt if not inc.image_prompt else inc.image_prompt
                invalidate(s, "draw")
            if prev.text != s.text:
                invalidate(s, "voice")
            moves[nid] = prev.id
        new.append(s)
    _move_scene_dirs(pid, set(old), moves)
    p.scenes = new
    if p.stage == "done":
        p.stage = "images"
        p.final = None
    store.save(p)
    return p.model_dump()

def _move_scene_dirs(pid, old_ids, moves):
    base = store.project_dir(pid) / "scenes"
    if not base.exists():
        return
    referenced = set(moves.values())
    for oid in old_ids - referenced:
        shutil.rmtree(base / oid, ignore_errors=True)
    for oid in referenced:
        if (base / oid).exists():
            os.replace(base / oid, base / f"_tmp_{oid}")
    for nid, oid in moves.items():
        if (base / f"_tmp_{oid}").exists():
            os.replace(base / f"_tmp_{oid}", base / nid)

@app.put("/api/projects/{pid}/settings")
def update_settings(pid: str, settings: Settings):
    _busy_check()
    p = _get(pid)
    invalidated = False
    if settings.voice != p.settings.voice:
        for s_ in p.scenes:
            if s_.status["voice"] == "done": invalidate(s_, "voice"); invalidated = True
    if settings.aspect != p.settings.aspect:
        for s_ in p.scenes: invalidate(s_, "image")
        invalidated = True
    if invalidated:
        p.final = None
        if p.stage == "done":
            p.stage = "images"
    settings.music_file = p.settings.music_file
    p.settings = settings; store.save(p)
    return p.model_dump()

@app.post("/api/projects/{pid}/approve/scenes")
def approve_scenes(pid: str):
    p = _get(pid)
    if p.stage not in ("scenes", "images"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _submit(pid, "images"); return {"ok": True}

@app.post("/api/projects/{pid}/segment")
def resegment(pid: str):
    p = _get(pid)
    if p.stage not in ("input", "scenes"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _busy_check()
    p.job_error = None; store.save(p)
    _submit(pid, "segment"); return {"ok": True}

class Regen(BaseModel):
    image_prompt: str | None = None

@app.post("/api/projects/{pid}/scenes/{sid}/regenerate")
def regenerate(pid: str, sid: str, body: Regen):
    p = _get(pid)
    _busy_check()
    s = next((x for x in p.scenes if x.id == sid), None)
    if not s: raise HTTPException(404, "Không có cảnh")
    if body.image_prompt: s.image_prompt = body.image_prompt
    store.save(p); _submit(pid, "images", only=[sid]); return {"ok": True}

@app.post("/api/projects/{pid}/render")
def render(pid: str):
    p = _get(pid)
    if p.stage not in ("images", "done"):
        raise HTTPException(409, "Không thể thực hiện ở bước này")
    _submit(pid, "render"); return {"ok": True}

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
