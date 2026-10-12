import asyncio
import json
import re
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
from .models import Scene, Settings
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

@app.get("/api/health")
def health():
    return {"checks": run_checks()}

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
        name = "music" + Path(music_file.filename).suffix.lower()
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
    new = []
    for i, s in enumerate(scenes, 1):
        prev = old.get(s.id)
        s.id = f"{i:02d}"
        if prev is None or (prev.visual_description, prev.elements) != (s.visual_description, s.elements):
            s.image_prompt = build_image_prompt(s); invalidate(s, "image")
        elif prev.text != s.text:
            s.status = dict(prev.status); invalidate(s, "voice")
        new.append(s)
    p.scenes = new
    if p.stage == "done":
        p.stage = "images"
    store.save(p)
    return p.model_dump()

@app.put("/api/projects/{pid}/settings")
def update_settings(pid: str, settings: Settings):
    _busy_check()
    p = _get(pid)
    if settings.voice != p.settings.voice:
        for s in p.scenes:
            if s.status["voice"] == "done": invalidate(s, "voice")
    settings.music_file = settings.music_file or p.settings.music_file
    p.settings = settings; store.save(p)
    return p.model_dump()

@app.post("/api/projects/{pid}/approve/scenes")
def approve_scenes(pid: str):
    _get(pid); _submit(pid, "images"); return {"ok": True}

class Regen(BaseModel):
    image_prompt: str | None = None

@app.post("/api/projects/{pid}/scenes/{sid}/regenerate")
def regenerate(pid: str, sid: str, body: Regen):
    p = _get(pid)
    s = next((x for x in p.scenes if x.id == sid), None)
    if not s: raise HTTPException(404, "Không có cảnh")
    if body.image_prompt: s.image_prompt = body.image_prompt
    store.save(p); _submit(pid, "images", only=[sid]); return {"ok": True}

@app.post("/api/projects/{pid}/render")
def render(pid: str):
    _get(pid); _submit(pid, "render"); return {"ok": True}

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
