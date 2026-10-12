# Whiteboard Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web app turning a Vietnamese script (text/.txt/.docx/.srt/.pdf) into a whiteboard hand-drawn video: Gemini (ADC) splits scenes + draws images, VieNeu v3 Turbo narrates, geeklee renderer animates, Remotion composes.

**Architecture:** FastAPI backend (`studio/` package) owns a file-based project store (`projects/<id>/project.json`) and a single worker thread running pipeline stages per scene. React/Vite frontend drives a 4-step wizard with two approval gates. Remotion package `composer/` renders the final video from a `props.json`, using the project dir as `--public-dir`.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, pydantic v2, google-genai (Vertex/ADC), vieneu, python-docx, pypdf, opencv-python, numpy, av, pytest · Node 20, Remotion 4, React 18, Vite 5, TypeScript.

## Global Constraints

- Single local user, Linux, CPU only; one job at a time.
- Gemini only via ADC: `genai.Client(vertexai=True, project=$GOOGLE_CLOUD_PROJECT, location=$GOOGLE_CLOUD_LOCATION or "global")`. No API keys.
- Model IDs from env: `GEMINI_TEXT_MODEL` (default `gemini-2.5-flash`), `GEMINI_IMAGE_MODEL` (default `gemini-2.5-flash-image`).
- Aspect: `"16:9"` → 1920×1080, scenes ~20–35 s; `"9:16"` → 1080×1920, scenes ~8–15 s.
- Image style (verbatim in every prompt): warm cream paper background `#F5EBD7`, dark grey sketch lines, accents only red/orange/blue, minimal Notion-like doodle, lots of whitespace, **no text/letters/numbers**, no photorealism/3D.
- `.srt` input: text only, timestamps ignored except as scene-boundary hints.
- Captions and music are independent per-project toggles; music ducks under narration.
- Vendored code keeps original LICENSE files (`studio/vendor/LICENSE-geeklee`, `LICENSE-vansyson`).
- All UI text Vietnamese.
- Every script/test runs from repo root `whiteboard-studio/`.

---

## File Structure

```
whiteboard-studio/
├── pyproject.toml
├── studio/
│   ├── __init__.py
│   ├── config.py        env + aspect presets
│   ├── models.py        pydantic: Project, Settings, Scene, Element, StepState
│   ├── store.py         load/save/create project dirs
│   ├── ingest.py        file → plain text
│   ├── llm.py           Gemini client, segment_script(), generate_image()
│   ├── voice.py         sentence split, VieNeu synth, word timings
│   ├── annotate.py      auto_annotate wrapper + timing mapping
│   ├── draw.py          subprocess wrapper around vendored renderer
│   ├── compose.py       props.json builder + remotion render
│   ├── pipeline.py      stage functions over a Project
│   ├── jobs.py          single worker thread + event bus
│   ├── checks.py        startup environment checks
│   ├── app.py           FastAPI routes
│   └── vendor/          stream_render.py, render_stream_whiteboard.py, auto_annotate.py, drawing-hand.png, LICENSE-*
├── composer/            Remotion project
├── frontend/            Vite React app
├── tests/
│   ├── conftest.py
│   ├── fixtures/        sample.txt/.srt/.docx/.pdf, scene.png
│   └── test_*.py
└── projects/            runtime data (gitignored)
```

---

### Task 1: Scaffold, config, models, store

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `studio/__init__.py`, `studio/config.py`, `studio/models.py`, `studio/store.py`, `tests/conftest.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `config.ASPECTS: dict[str, tuple[int,int]]`, `config.SCENE_SECONDS: dict[str, tuple[int,int]]`, `config.PROJECTS_DIR: Path` (env `STUDIO_PROJECTS_DIR`, default `./projects`)
  - `models.StepState = Literal["pending","running","done","error"]`
  - `models.Element(label:str, say:str)`
  - `models.Scene(id:str, text:str, key_idea:str, visual_description:str, elements:list[Element], image_prompt:str="", status:dict[str,StepState], error:str|None, duration_ms:int|None)`; status keys: `image, voice, draw`
  - `models.Settings(aspect:Literal["16:9","9:16"]="16:9", voice:str="Hải Đăng", captions:bool=True, music:bool=False, music_file:str|None=None)`
  - `models.Project(id, title, created_at, settings, source_text, stage:Literal["input","scenes","images","rendering","done"], scenes:list[Scene], final:str|None, job_error:str|None)`
  - `store.create_project(title:str, settings:Settings, source_text:str) -> Project`, `store.load(pid)->Project`, `store.save(p)->None`, `store.project_dir(pid)->Path`, `store.scene_dir(pid, scene_id)->Path`, `store.list_projects()->list[Project]`

- [ ] **Step 1: Write scaffolding**

`pyproject.toml`:
```toml
[project]
name = "whiteboard-studio"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "fastapi>=0.110", "uvicorn[standard]>=0.29", "pydantic>=2.6", "python-multipart>=0.0.9",
  "google-genai>=1.0", "python-docx>=1.1", "pypdf>=4.0",
  "opencv-python>=4.9", "numpy>=1.26", "av>=12", "soundfile>=0.12",
]
[project.optional-dependencies]
voice = ["vieneu"]
dev = ["pytest>=8", "httpx>=0.27", "reportlab>=4"]
[tool.setuptools]
packages = ["studio"]
[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.gitignore`:
```
projects/
.venv/
node_modules/
__pycache__/
composer/out/
frontend/dist/
```

`studio/__init__.py`: empty.

`studio/config.py`:
```python
import os
from pathlib import Path

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
SCENE_SECONDS = {"16:9": (20, 35), "9:16": (8, 15)}
FPS = 30
PROJECTS_DIR = Path(os.environ.get("STUDIO_PROJECTS_DIR", "projects")).resolve()
ROOT = Path(__file__).resolve().parent.parent
COMPOSER_DIR = ROOT / "composer"
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
```

`studio/models.py`:
```python
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

StepState = Literal["pending", "running", "done", "error"]
STEPS = ("image", "voice", "draw")

class Element(BaseModel):
    label: str
    say: str

class Scene(BaseModel):
    id: str
    text: str
    key_idea: str = ""
    visual_description: str = ""
    elements: list[Element] = Field(default_factory=list)
    image_prompt: str = ""
    status: dict[str, StepState] = Field(default_factory=lambda: {s: "pending" for s in STEPS})
    error: str | None = None
    duration_ms: int | None = None

class Settings(BaseModel):
    aspect: Literal["16:9", "9:16"] = "16:9"
    voice: str = "Hải Đăng"
    captions: bool = True
    music: bool = False
    music_file: str | None = None

class Project(BaseModel):
    id: str
    title: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    settings: Settings = Field(default_factory=Settings)
    source_text: str = ""
    stage: Literal["input", "scenes", "images", "rendering", "done"] = "input"
    scenes: list[Scene] = Field(default_factory=list)
    final: str | None = None
    job_error: str | None = None
```

`studio/store.py`:
```python
import os
import uuid
from pathlib import Path
from . import config
from .models import Project, Settings

def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid

def scene_dir(pid: str, scene_id: str) -> Path:
    d = project_dir(pid) / "scenes" / scene_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def save(p: Project) -> None:
    d = project_dir(p.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    tmp.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, d / "project.json")

def load(pid: str) -> Project:
    f = project_dir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    return Project.model_validate_json(f.read_text(encoding="utf-8"))

def create_project(title: str, settings: Settings, source_text: str) -> Project:
    p = Project(id=uuid.uuid4().hex[:10], title=title or "Dự án mới", settings=settings, source_text=source_text)
    save(p)
    return p

def list_projects() -> list[Project]:
    if not config.PROJECTS_DIR.exists():
        return []
    out = [load(d.name) for d in config.PROJECTS_DIR.iterdir() if (d / "project.json").exists()]
    return sorted(out, key=lambda p: p.created_at, reverse=True)
```

`tests/conftest.py`:
```python
import pytest
from studio import config

@pytest.fixture(autouse=True)
def tmp_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path / "projects"
```

- [ ] **Step 2: Write failing test** `tests/test_store.py`:
```python
from studio import store
from studio.models import Settings, Scene

def test_create_load_roundtrip():
    p = store.create_project("Thử", Settings(aspect="9:16"), "xin chào")
    p.scenes.append(Scene(id="01", text="a"))
    store.save(p)
    q = store.load(p.id)
    assert q.settings.aspect == "9:16"
    assert q.scenes[0].status == {"image": "pending", "voice": "pending", "draw": "pending"}
    assert [x.id for x in store.list_projects()] == [p.id]

def test_scene_dir_created():
    p = store.create_project("x", Settings(), "")
    assert store.scene_dir(p.id, "01").is_dir()
```

- [ ] **Step 3: Install and run**
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
pytest tests/test_store.py -v
```
Expected: 2 passed (write tests before models only if you want to see FAIL first: `ModuleNotFoundError: studio.store`).

- [ ] **Step 4: Commit**
```bash
git add -A && git commit -m "feat: scaffold project store and models"
```

---

### Task 2: Ingest (txt/docx/srt/pdf)

**Files:**
- Create: `studio/ingest.py`, `tests/test_ingest.py`, `tests/fixtures/` (generated in test)

**Interfaces:**
- Produces: `ingest.extract_text(filename:str, data:bytes) -> str` (raises `ValueError("Định dạng không hỗ trợ: …")`); `ingest.srt_blocks(text:str) -> list[str]` (subtitle texts without indices/timestamps).

- [ ] **Step 1: Failing test** `tests/test_ingest.py`:
```python
import io
import pytest
from docx import Document
from reportlab.pdfgen import canvas
from studio.ingest import extract_text

SRT = "1\n00:00:01,000 --> 00:00:03,000\nXin chào\n\n2\n00:00:03,500 --> 00:00:05,000\nThế giới\n"

def test_txt():
    assert extract_text("a.txt", "Lạm phát là gì?".encode()) == "Lạm phát là gì?"

def test_srt_strips_timestamps():
    assert extract_text("a.srt", SRT.encode()) == "Xin chào\nThế giới"

def test_docx():
    d = Document(); d.add_paragraph("Đoạn một"); d.add_paragraph("Đoạn hai")
    buf = io.BytesIO(); d.save(buf)
    assert extract_text("a.docx", buf.getvalue()) == "Đoạn một\nĐoạn hai"

def test_pdf():
    buf = io.BytesIO(); c = canvas.Canvas(buf); c.drawString(72, 720, "Hello PDF"); c.save()
    assert "Hello PDF" in extract_text("a.pdf", buf.getvalue())

def test_unsupported():
    with pytest.raises(ValueError):
        extract_text("a.exe", b"x")
```

- [ ] **Step 2: Run** `pytest tests/test_ingest.py -v` → FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `studio/ingest.py`:
```python
import io
import re
from pathlib import Path

_TS = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->")

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1258"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def srt_blocks(text: str) -> list[str]:
    blocks = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        lines = [l for l in lines if not l.strip().isdigit() and not _TS.match(l.strip())]
        if lines:
            blocks.append(" ".join(l.strip() for l in lines))
    return blocks

def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return _decode(data).strip()
    if ext == ".srt":
        return "\n".join(srt_blocks(_decode(data)))
    if ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = [pg.extract_text() or "" for pg in PdfReader(io.BytesIO(data)).pages]
        return "\n".join(t.strip() for t in pages if t.strip())
    raise ValueError(f"Định dạng không hỗ trợ: {ext}")
```

- [ ] **Step 4: Run** `pytest tests/test_ingest.py -v` → 5 passed.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: ingest txt/docx/srt/pdf"`

---

### Task 3: Gemini via ADC — scene segmentation + image generation

**Files:**
- Create: `studio/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `models.Scene`, `models.Element`, `config.*`
- Produces:
  - `llm.get_client() -> genai.Client` (cached; Vertex/ADC)
  - `llm.segment_script(text:str, aspect:str, client=None) -> list[Scene]` (ids `"01","02",…`; `image_prompt` filled via `build_image_prompt`)
  - `llm.build_image_prompt(scene:Scene) -> str`
  - `llm.generate_image(prompt:str, aspect:str, out:Path, client=None) -> Path` (PNG)
  - `llm.LLMError(Exception)`

- [ ] **Step 1: Failing test** `tests/test_llm.py`:
```python
import json
from types import SimpleNamespace
import pytest
from studio import llm

class FakeModels:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    def generate_content(self, model, contents, config=None):
        self.calls.append((model, contents, config))
        r = self.responses.pop(0)
        if isinstance(r, Exception): raise r
        return r

def text_resp(obj): return SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), candidates=[])

GOOD = {"scenes": [
    {"text": "Lạm phát là khi giá tăng.", "key_idea": "định nghĩa",
     "visual_description": "giỏ hàng và mũi tên đi lên",
     "elements": [{"label": "giỏ hàng", "say": "giá"}, {"label": "mũi tên", "say": "tăng"}]},
]}

def test_segment_parses_and_ids():
    fake = SimpleNamespace(models=FakeModels([text_resp(GOOD)]))
    scenes = llm.segment_script("Lạm phát là khi giá tăng.", "16:9", client=fake)
    assert [s.id for s in scenes] == ["01"]
    assert scenes[0].elements[1].say == "tăng"
    assert "#F5EBD7" in scenes[0].image_prompt
    prompt = fake.models.calls[0][1]
    assert "20" in prompt and "35" in prompt   # 16:9 duration hint

def test_segment_retries_bad_json():
    fake = SimpleNamespace(models=FakeModels([SimpleNamespace(text="not json", candidates=[]), text_resp(GOOD)]))
    assert len(llm.segment_script("x", "9:16", client=fake)) == 1

def test_segment_gives_up():
    bad = SimpleNamespace(text="{}", candidates=[])
    fake = SimpleNamespace(models=FakeModels([bad, bad, bad]))
    with pytest.raises(llm.LLMError):
        llm.segment_script("x", "16:9", client=fake)

def test_generate_image_writes_png(tmp_path):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNGfake", mime_type="image/png"), text=None)
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
    fake = SimpleNamespace(models=FakeModels([resp]))
    out = llm.generate_image("p", "9:16", tmp_path / "image.png", client=fake)
    assert out.read_bytes() == b"\x89PNGfake"
    assert fake.models.calls[0][2].image_config.aspect_ratio == "9:16"
```

- [ ] **Step 2: Run** `pytest tests/test_llm.py -v` → FAIL.

- [ ] **Step 3: Implement** `studio/llm.py`:
```python
import json
import time
from functools import lru_cache
from pathlib import Path
from google import genai
from google.genai import types, errors
from . import config
from .models import Element, Scene

class LLMError(Exception):
    pass

STYLE = (
    "Minimal hand-drawn sketch illustration, Notion-like restrained doodle aesthetic. "
    "Warm cream paper background exactly #F5EBD7, dark grey sketch lines; "
    "only small conceptual accents in red, orange or blue. Simple outlines, lots of empty space, "
    "clean background, objects clearly separated from each other. "
    "ABSOLUTELY NO text, words, letters, numbers or labels. No photorealism, no 3D, no painterly texture."
)

SEGMENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {"scenes": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING"},
            "key_idea": {"type": "STRING"},
            "visual_description": {"type": "STRING"},
            "elements": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "label": {"type": "STRING"}, "say": {"type": "STRING"}}, "required": ["label", "say"]}},
        },
        "required": ["text", "key_idea", "visual_description", "elements"],
    }}},
    "required": ["scenes"],
}

@lru_cache(maxsize=1)
def get_client() -> "genai.Client":
    if not config.GCP_PROJECT:
        raise LLMError("Thiếu GOOGLE_CLOUD_PROJECT")
    return genai.Client(vertexai=True, project=config.GCP_PROJECT, location=config.GCP_LOCATION)

def _call(client, **kw):
    for attempt in range(4):
        try:
            return client.models.generate_content(**kw)
        except errors.APIError as e:
            if getattr(e, "code", None) in (429, 500, 503) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise LLMError(f"Gemini lỗi: {e}") from e

def build_image_prompt(scene: Scene) -> str:
    objs = ", ".join(e.label for e in scene.elements)
    return f"{STYLE}\nScene: {scene.visual_description}\nDistinct objects to draw: {objs}."

def segment_script(text: str, aspect: str, client=None) -> list[Scene]:
    client = client or get_client()
    lo, hi = config.SCENE_SECONDS[aspect]
    prompt = (
        "Bạn là biên tập viên video giải thích dạng vẽ bảng trắng tiếng Việt.\n"
        f"Chia kịch bản sau thành các cảnh theo ý nội dung, mỗi cảnh đọc khoảng {lo}-{hi} giây "
        "(~4 âm tiết/giây). Giữ NGUYÊN văn lời đọc, không thêm bớt, không bỏ sót câu nào; nối các cảnh lại phải ra đúng kịch bản.\n"
        "Mỗi cảnh: text (lời đọc), key_idea (ý chính ngắn), visual_description (mô tả hình minh hoạ bằng tiếng Anh, "
        "đơn giản, 2-5 đối tượng tách rời), elements (2-5 đối tượng theo thứ tự vẽ; label tiếng Anh ngắn; "
        "say = cụm từ NGUYÊN VĂN xuất hiện trong text, lúc đọc tới thì vẽ đối tượng đó).\n\n"
        f"KỊCH BẢN:\n{text}"
    )
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=SEGMENT_SCHEMA,
                                      temperature=0.3)
    last = None
    for _ in range(3):
        resp = _call(client, model=config.TEXT_MODEL, contents=prompt, config=cfg)
        try:
            data = json.loads(resp.text)
            raw = data["scenes"]
            if not raw:
                raise ValueError("empty scenes")
            scenes = []
            for i, s in enumerate(raw, 1):
                sc = Scene(id=f"{i:02d}", text=s["text"].strip(), key_idea=s.get("key_idea", ""),
                           visual_description=s["visual_description"],
                           elements=[Element(**e) for e in s["elements"]])
                sc.image_prompt = build_image_prompt(sc)
                scenes.append(sc)
            return scenes
        except (ValueError, KeyError, TypeError) as e:
            last = e
    raise LLMError(f"Gemini trả về dữ liệu chia cảnh không hợp lệ: {last}")

def generate_image(prompt: str, aspect: str, out: Path, client=None) -> Path:
    client = client or get_client()
    cfg = types.GenerateContentConfig(response_modalities=["IMAGE"],
                                      image_config=types.ImageConfig(aspect_ratio=aspect))
    resp = _call(client, model=config.IMAGE_MODEL, contents=prompt, config=cfg)
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(part.inline_data.data)
                return out
    raise LLMError("Gemini không trả về ảnh")
```

- [ ] **Step 4: Run** `pytest tests/test_llm.py -v` → 4 passed.
- [ ] **Step 5: Manual ADC smoke (optional, needs credentials)**
```bash
gcloud auth application-default login   # once
GOOGLE_CLOUD_PROJECT=<id> python -c "from studio import llm; print([s.key_idea for s in llm.segment_script('Lạm phát là khi giá cả tăng đều. Tiền mất giá.', '9:16')])"
```
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: gemini ADC segmentation and image generation"`

---

### Task 4: Voice — VieNeu per sentence with word timings

VieNeu gives no timestamps. We synthesize **per sentence**, measure each sentence's duration, insert fixed pauses, and spread word times inside a sentence proportionally to character length.

**Files:**
- Create: `studio/voice.py`, `tests/test_voice.py`

**Interfaces:**
- Produces:
  - `voice.Word = TypedDict(text:str, start_ms:int, end_ms:int)`
  - `voice.split_sentences(text:str) -> list[str]`
  - `voice.synthesize(text:str, voice_name:str, out_wav:Path, tts=None) -> list[Word]` — writes mono 24k/whatever-rate WAV (16-bit) and `out_wav.with_name("words.json")`; returns words.
  - `voice.get_tts()` (cached `vieneu.Vieneu(mode=os.environ.get("VIENEU_MODE","v3turbo"))`)
  - Constants: `LEAD_MS=300`, `GAP_MS=250`, `TAIL_MS=600`

- [ ] **Step 1: Failing test** `tests/test_voice.py`:
```python
import json
import numpy as np
import soundfile as sf
from studio import voice

class FakeTTS:
    sample_rate = 24000
    def resolve_voice_name(self, v): return v
    def get_preset_voice(self, v): return v
    def infer(self, text, voice=None):
        return np.zeros(int(self.sample_rate * 0.1 * len(text.split())), dtype=np.float32)  # 100ms/word

def test_split_sentences():
    assert voice.split_sentences("Một hai. Ba bốn? Năm!\nSáu") == ["Một hai.", "Ba bốn?", "Năm!", "Sáu"]

def test_synthesize_timings(tmp_path):
    words = voice.synthesize("Một hai. Ba bốn năm.", "Hải Đăng", tmp_path / "voice.wav", tts=FakeTTS())
    assert [w["text"] for w in words] == ["Một", "hai.", "Ba", "bốn", "năm."]
    assert words[0]["start_ms"] == voice.LEAD_MS
    assert words[1]["end_ms"] == voice.LEAD_MS + 200
    assert words[2]["start_ms"] == voice.LEAD_MS + 200 + voice.GAP_MS
    data, sr = sf.read(tmp_path / "voice.wav")
    expect = voice.LEAD_MS + 200 + voice.GAP_MS + 300 + voice.TAIL_MS
    assert abs(len(data) / sr * 1000 - expect) < 2
    assert json.loads((tmp_path / "words.json").read_text())[4]["text"] == "năm."
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `studio/voice.py`:
```python
import json
import os
import re
import threading
from pathlib import Path
from typing import TypedDict
import numpy as np
import soundfile as sf

LEAD_MS, GAP_MS, TAIL_MS = 300, 250, 600
_LOCK = threading.Lock()
_TTS = {}

class Word(TypedDict):
    text: str
    start_ms: int
    end_ms: int

def get_tts():
    if "t" not in _TTS:
        try:
            from vieneu import Vieneu
        except ImportError as e:
            raise RuntimeError("Chưa cài VieNeu: pip install vieneu") from e
        _TTS["t"] = Vieneu(mode=os.environ.get("VIENEU_MODE", "v3turbo"))
    return _TTS["t"]

def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]

def _silence(ms: int, rate: int) -> np.ndarray:
    return np.zeros(int(rate * ms / 1000), dtype=np.float32)

def synthesize(text: str, voice_name: str, out_wav: Path, tts=None) -> list[Word]:
    tts = tts or get_tts()
    rate = tts.sample_rate
    chunks = [_silence(LEAD_MS, rate)]
    t = LEAD_MS
    words: list[Word] = []
    sentences = split_sentences(text)
    for i, sent in enumerate(sentences):
        with _LOCK:
            if tts.resolve_voice_name(voice_name) is None:
                raise RuntimeError(f"Không có giọng VieNeu {voice_name!r}")
            pcm = np.asarray(tts.infer(sent, voice=tts.get_preset_voice(voice_name)), dtype=np.float32).reshape(-1)
        dur = len(pcm) * 1000 / rate
        toks = sent.split()
        total_chars = sum(len(w) for w in toks) or 1
        acc = 0.0
        for w in toks:
            s = t + dur * acc / total_chars
            acc += len(w)
            words.append({"text": w, "start_ms": round(s), "end_ms": round(t + dur * acc / total_chars)})
        chunks.append(pcm)
        t += dur
        if i < len(sentences) - 1:
            chunks.append(_silence(GAP_MS, rate)); t += GAP_MS
    chunks.append(_silence(TAIL_MS, rate))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, np.concatenate(chunks), rate, subtype="PCM_16")
    out_wav.with_name("words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words

def wav_duration_ms(path: Path) -> int:
    info = sf.info(path)
    return round(info.frames * 1000 / info.samplerate)
```

- [ ] **Step 4: Run** `pytest tests/test_voice.py -v` → 2 passed.
- [ ] **Step 5: Manual real-voice smoke**
```bash
pip install -e '.[voice]'
python -c "from pathlib import Path; from studio import voice; print(voice.synthesize('Xin chào các bạn. Hôm nay ta nói về lạm phát.', 'Hải Đăng', Path('/tmp/v/voice.wav'))[:3])"
ffprobe -v error -show_entries format=duration /tmp/v/voice.wav
```
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: VieNeu per-sentence synthesis with word timings"`

---

### Task 5: Vendor renderer + annotation with narration timing

**Files:**
- Create: `studio/vendor/` (copied), `studio/annotate.py`, `tests/test_annotate.py`, `tests/fixtures/scene.png` (generated by test helper)

**Interfaces:**
- Consumes: `voice.Word`, `models.Element`
- Produces:
  - `annotate.build_annotation(image:Path, elements:list[Element], words:list[Word], duration_ms:int) -> dict` (geeklee annotation schema)
  - `annotate.find_phrase_ms(words, phrase) -> int|None`

- [ ] **Step 1: Vendor files**
```bash
mkdir -p studio/vendor
cp ../refs/geeklee/scripts/stream_render.py ../refs/geeklee/scripts/render_stream_whiteboard.py studio/vendor/
cp ../refs/geeklee/assets/drawing-hand.png studio/vendor/
cp ../refs/vansyson/scripts/auto_annotate.py studio/vendor/
cp ../refs/geeklee/LICENSE studio/vendor/LICENSE-geeklee
cp ../refs/vansyson/LICENSE studio/vendor/LICENSE-vansyson
grep -n "DEFAULT_HAND" studio/vendor/render_stream_whiteboard.py | head -3
```
If `DEFAULT_HAND` points to `../assets/drawing-hand.png`, change that line to `DEFAULT_HAND = Path(__file__).resolve().parent / "drawing-hand.png"`. `auto_annotate.py` already does `sys.path.insert(0, its dir)` + `import stream_render as sr` — works unchanged.

- [ ] **Step 2: Failing test** `tests/test_annotate.py`:
```python
import cv2
import numpy as np
from studio.annotate import build_annotation, find_phrase_ms
from studio.models import Element

WORDS = [{"text": t, "start_ms": 300 + i * 400, "end_ms": 300 + i * 400 + 350}
         for i, t in enumerate("Giá cả tăng nhanh, tiền mất giá.".split())]

def make_scene(path):
    img = np.full((540, 960, 3), (215, 235, 245), np.uint8)   # BGR of #F5EBD7
    cv2.circle(img, (200, 270), 80, (60, 60, 60), 6)
    cv2.rectangle(img, (650, 170), (850, 370), (60, 60, 60), 6)
    cv2.imwrite(str(path), img)
    return path

def test_find_phrase_ms():
    assert find_phrase_ms(WORDS, "tiền mất") == 300 + 4 * 400
    assert find_phrase_ms(WORDS, "TĂNG") == 300 + 2 * 400
    assert find_phrase_ms(WORDS, "không có") is None

def test_build_annotation_uses_phrase_times(tmp_path):
    img = make_scene(tmp_path / "image.png")
    els = [Element(label="coin", say="tăng"), Element(label="box", say="tiền mất")]
    ann = build_annotation(img, els, WORDS, 6000)
    assert ann["sceneDurationMs"] == 6000
    assert len(ann["elements"]) == 2
    starts = [e["reveal"]["startMs"] for e in ann["elements"]]
    assert starts == [1100, 1900]
    assert ann["elements"][0]["label"] == "coin"
    last = ann["elements"][-1]["reveal"]
    assert last["startMs"] + last["durationMs"] <= 6000 - 300
```

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement** `studio/annotate.py`:
```python
import re
import sys
import unicodedata
from pathlib import Path
from .models import Element

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
import auto_annotate  # noqa: E402

def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", s).lower())

def find_phrase_ms(words: list[dict], phrase: str) -> int | None:
    target = [_norm(t) for t in phrase.split() if _norm(t)]
    toks = [_norm(w["text"]) for w in words]
    if not target:
        return None
    for i in range(len(toks) - len(target) + 1):
        if toks[i:i + len(target)] == target:
            return words[i]["start_ms"]
    return None

def build_annotation(image: Path, elements: list[Element], words: list[dict], duration_ms: int) -> dict:
    k = max(1, len(elements)) if elements else None
    ann = auto_annotate.annotate(image, k=k, labels=[e.label for e in elements] or None,
                                 says=[e.say for e in elements] or None, duration_ms=duration_ms)
    els = ann["elements"]
    n = len(els)
    end_limit = duration_ms - 300
    slot = (end_limit - 300) / max(1, n)
    starts = []
    for i, e in enumerate(els):
        ms = find_phrase_ms(words, e.get("say", "")) if e.get("say") else None
        fallback = int(300 + i * slot)
        ms = fallback if ms is None else ms
        if starts and ms <= starts[-1]:
            ms = starts[-1] + 400
        starts.append(min(ms, end_limit - 800))
    for i, e in enumerate(els):
        nxt = starts[i + 1] if i + 1 < n else end_limit
        e["reveal"]["startMs"] = starts[i]
        e["reveal"]["durationMs"] = max(800, min(int(slot * 1.2), nxt - starts[i]))
        e["subtitle"] = e.get("say", "")
    ann["sceneDurationMs"] = int(duration_ms)
    return ann
```

- [ ] **Step 5: Run** `pytest tests/test_annotate.py -v` → 2 passed. (If `auto_annotate` merges both shapes into one box, pass `merge_ratio` is internal; the test image's shapes are 450px apart, which is well above the 1.4% merge gap.)
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: vendor whiteboard renderer, narration-timed annotation"`

---

### Task 6: Draw wrapper

**Files:**
- Create: `studio/draw.py`, `tests/test_draw.py`

**Interfaces:**
- Consumes: annotation dict from Task 5
- Produces: `draw.render_clip(image:Path, annotation:dict, out:Path, size:tuple[int,int], fps:int=30) -> Path` (silent MP4; raises `RuntimeError` with stderr tail). Resizes image to `size` first and scales annotation coordinates accordingly — actually the renderer handles scaling from `canvas`, so we only pass `--fps`.

- [ ] **Step 1: Check renderer flags** `python studio/vendor/render_stream_whiteboard.py --help` — confirm `--fps`, `--total-ms`. Output size follows image size; Task 8 ensures images are resized to the aspect preset before annotation.

- [ ] **Step 2: Failing test** `tests/test_draw.py` (slow, real render of a tiny scene):
```python
import json
import subprocess
from studio.annotate import build_annotation
from studio.draw import render_clip
from studio.models import Element
from tests.test_annotate import make_scene, WORDS

def test_render_clip(tmp_path):
    img = make_scene(tmp_path / "image.png")
    ann = build_annotation(img, [Element(label="a", say="tăng"), Element(label="b", say="tiền")], WORDS, 3000)
    out = render_clip(img, ann, tmp_path / "clip.mp4", fps=15)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json",
                                                "-show_format", "-show_streams", str(out)]))
    assert abs(float(probe["format"]["duration"]) - 3.0) < 0.3
    assert probe["streams"][0]["width"] == 960
```

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement** `studio/draw.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

RENDERER = Path(__file__).resolve().parent / "vendor" / "render_stream_whiteboard.py"

def render_clip(image: Path, annotation: dict, out: Path, fps: int = 30) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ann_path = out.with_name("annotation.json")
    ann_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [sys.executable, str(RENDERER), str(image), str(ann_path), str(out),
           "--fps", str(fps), "--total-ms", str(annotation["sceneDurationMs"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("Lỗi vẽ cảnh: " + (r.stderr or r.stdout)[-800:])
    return out
```
(Drop the `size` parameter from the interface: size comes from the image.)

- [ ] **Step 5: Run** `pytest tests/test_draw.py -v` → PASS (may take ~10–30 s).
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: whiteboard clip renderer wrapper"`

---

### Task 7: Remotion composer + compose.py

**Files:**
- Create: `composer/package.json`, `composer/tsconfig.json`, `composer/src/index.ts`, `composer/src/Root.tsx`, `composer/src/FinalVideo.tsx`, `composer/src/Captions.tsx`, `studio/compose.py`, `tests/test_compose.py`

**Interfaces:**
- Consumes: project dir layout `scenes/<id>/{clip.mp4, voice.wav, words.json}`
- Produces:
  - Remotion composition id `FinalVideo`, props `VideoProps = {fps, width, height, captions:boolean, music:string|null, scenes:{clip:string, audio:string, durationInFrames:number, words:{text,start_ms,end_ms}[]}[]}` (paths relative to public dir)
  - `compose.build_props(project:Project) -> dict`
  - `compose.render_final(project:Project, on_progress=None) -> Path` (writes `final.mp4` in project dir)

- [ ] **Step 1: Remotion package**

`composer/package.json`:
```json
{
  "name": "whiteboard-composer",
  "private": true,
  "scripts": { "studio": "remotion studio src/index.ts" },
  "dependencies": {
    "@remotion/cli": "4.0.290",
    "remotion": "4.0.290",
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": { "typescript": "5.6.3", "@types/react": "18.3.12" }
}
```

`composer/tsconfig.json`:
```json
{ "compilerOptions": { "target": "ES2020", "module": "ESNext", "jsx": "react-jsx", "strict": true,
  "moduleResolution": "bundler", "skipLibCheck": true } }
```

`composer/src/index.ts`:
```ts
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";
registerRoot(RemotionRoot);
```

`composer/src/Root.tsx`:
```tsx
import { Composition } from "remotion";
import { FinalVideo, VideoProps } from "./FinalVideo";

const defaults: VideoProps = { fps: 30, width: 1920, height: 1080, captions: true, music: null, scenes: [] };

export const RemotionRoot = () => (
  <Composition
    id="FinalVideo"
    component={FinalVideo}
    defaultProps={defaults}
    fps={30}
    width={1920}
    height={1080}
    durationInFrames={30}
    calculateMetadata={({ props }) => ({
      fps: props.fps, width: props.width, height: props.height,
      durationInFrames: Math.max(1, props.scenes.reduce((a, s) => a + s.durationInFrames, 0)),
    })}
  />
);
```

`composer/src/FinalVideo.tsx`:
```tsx
import { AbsoluteFill, Audio, OffthreadVideo, Series, staticFile, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { Captions, Word } from "./Captions";

export type SceneProps = { clip: string; audio: string; durationInFrames: number; words: Word[] };
export type VideoProps = { fps: number; width: number; height: number; captions: boolean; music: string | null; scenes: SceneProps[] };

const Music: React.FC<{ src: string; scenes: SceneProps[] }> = ({ src, scenes }) => {
  const { fps } = useVideoConfig();
  // speech intervals in absolute frames, used for ducking
  const spans: [number, number][] = [];
  let offset = 0;
  for (const s of scenes) {
    if (s.words.length) spans.push([offset + (s.words[0].start_ms / 1000) * fps, offset + (s.words[s.words.length - 1].end_ms / 1000) * fps]);
    offset += s.durationInFrames;
  }
  return (
    <Audio src={staticFile(src)} loop volume={(f) => {
      const speaking = spans.some(([a, b]) => f >= a - 8 && f <= b + 8);
      return speaking ? 0.08 : 0.3;
    }} />
  );
};

export const FinalVideo: React.FC<VideoProps> = ({ scenes, captions, music }) => (
  <AbsoluteFill style={{ backgroundColor: "#F5EBD7" }}>
    <Series>
      {scenes.map((s, i) => (
        <Series.Sequence key={i} durationInFrames={s.durationInFrames}>
          <OffthreadVideo src={staticFile(s.clip)} muted />
          <Audio src={staticFile(s.audio)} />
          {captions && <Captions words={s.words} />}
        </Series.Sequence>
      ))}
    </Series>
    {music && <Music src={music} scenes={scenes} />}
  </AbsoluteFill>
);
```

`composer/src/Captions.tsx`:
```tsx
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

export type Word = { text: string; start_ms: number; end_ms: number };

// group words into lines of max ~7 words, breaking after sentence punctuation
const lines = (words: Word[]) => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= 7 || /[.!?…]$/.test(w.text)) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
};

export const Captions: React.FC<{ words: Word[] }> = ({ words }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ms = (frame / fps) * 1000;
  const line = lines(words).find((l) => ms >= l[0].start_ms - 100 && ms <= l[l.length - 1].end_ms + 300);
  if (!line) return null;
  const portrait = height > width;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: portrait ? 260 : 70 }}>
      <div style={{ background: "rgba(40,40,40,0.72)", borderRadius: 14, padding: "10px 22px", maxWidth: "86%",
        textAlign: "center", fontFamily: "Be Vietnam Pro, Arial, sans-serif", fontWeight: 700, fontSize: portrait ? 54 : 46, lineHeight: 1.3 }}>
        {line.map((w, i) => (
          <span key={i} style={{ color: ms >= w.start_ms ? "#FFC857" : "#FFFFFF" }}>{w.text} </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
```

```bash
cd composer && npm install && npx tsc --noEmit && cd ..
```
Expected: no TS errors. (Remove unused imports `useCurrentFrame, interpolate` from FinalVideo.tsx if tsc complains under `noUnusedLocals` — not enabled here.)

- [ ] **Step 2: Failing test** `tests/test_compose.py`:
```python
import json
from studio import compose, store, config
from studio.models import Settings, Scene

def test_build_props(tmp_projects):
    p = store.create_project("t", Settings(aspect="9:16", captions=False, music=True, music_file="uploads/m.mp3"), "")
    p.scenes = [Scene(id="01", text="a", duration_ms=2000), Scene(id="02", text="b", duration_ms=1010)]
    for s in p.scenes:
        (store.scene_dir(p.id, s.id) / "words.json").write_text(json.dumps([{"text": "a", "start_ms": 0, "end_ms": 10}]))
    props = compose.build_props(p)
    assert (props["width"], props["height"], props["fps"]) == (1080, 1920, config.FPS)
    assert props["captions"] is False and props["music"] == "uploads/m.mp3"
    assert props["scenes"][0] == {"clip": "scenes/01/clip.mp4", "audio": "scenes/01/voice.wav",
                                  "durationInFrames": 60, "words": [{"text": "a", "start_ms": 0, "end_ms": 10}]}
    assert props["scenes"][1]["durationInFrames"] == 31
```

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement** `studio/compose.py`:
```python
import json
import math
import re
import subprocess
from pathlib import Path
from . import config, store
from .models import Project

def build_props(p: Project) -> dict:
    w, h = config.ASPECTS[p.settings.aspect]
    scenes = []
    for s in p.scenes:
        d = store.scene_dir(p.id, s.id)
        words = json.loads((d / "words.json").read_text(encoding="utf-8")) if (d / "words.json").exists() else []
        scenes.append({"clip": f"scenes/{s.id}/clip.mp4", "audio": f"scenes/{s.id}/voice.wav",
                       "durationInFrames": math.ceil(s.duration_ms * config.FPS / 1000), "words": words})
    music = p.settings.music_file if p.settings.music and p.settings.music_file else None
    return {"fps": config.FPS, "width": w, "height": h, "captions": p.settings.captions,
            "music": music, "scenes": scenes}

_PROG = re.compile(r"(\d+)/(\d+)")

def render_final(p: Project, on_progress=None) -> Path:
    pdir = store.project_dir(p.id)
    props_file = pdir / "props.json"
    props_file.write_text(json.dumps(build_props(p), ensure_ascii=False), encoding="utf-8")
    out = pdir / "final.mp4"
    cmd = ["npx", "remotion", "render", "src/index.ts", "FinalVideo", str(out),
           f"--props={props_file}", f"--public-dir={pdir}", "--concurrency=50%"]
    proc = subprocess.Popen(cmd, cwd=config.COMPOSER_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in proc.stdout:
        tail = (tail + [line])[-30:]
        m = _PROG.search(line)
        if on_progress and m and "Rendered" in line:
            on_progress(int(m.group(1)) / max(1, int(m.group(2))))
    if proc.wait() != 0 or not out.exists():
        raise RuntimeError("Remotion lỗi:\n" + "".join(tail))
    return out
```

- [ ] **Step 5: Run** `pytest tests/test_compose.py -v` → PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: remotion composer with captions and ducked music"`

---

### Task 8: Pipeline stages + job worker

**Files:**
- Create: `studio/pipeline.py`, `studio/jobs.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `llm.segment_script/generate_image`, `voice.synthesize/wav_duration_ms`, `annotate.build_annotation`, `draw.render_clip`, `compose.render_final`, `store.*`
- Produces:
  - `pipeline.Deps` dataclass with callables `segment, gen_image, synth, draw, render` (defaults = real ones; tests inject fakes)
  - `pipeline.run_segment(pid, deps)` → stage `"scenes"`
  - `pipeline.run_images(pid, deps, only:list[str]|None=None)` → stage `"images"`; resizes image to aspect preset (cover-crop) and saves `image.png`
  - `pipeline.run_render(pid, deps)` → voice+annotate+draw for scenes whose step != done, then compose; stage `"done"`, sets `final="final.mp4"`
  - `pipeline.invalidate(scene, from_step:str)` resets status from that step onward
  - `jobs.JOBS: JobRunner` with `submit(pid:str, kind:Literal["segment","images","render"], **kw) -> bool` (False if busy), `subscribe() -> queue.Queue`, `busy:bool`; events `{"pid","type":"progress"|"done"|"error","msg","pct"}`

- [ ] **Step 1: Failing test** `tests/test_pipeline.py`:
```python
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
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `studio/pipeline.py`:
```python
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
```
Note: `wav_duration_ms` in fake path reads the 1 s wav → `duration_ms == 1000` as asserted.

`studio/jobs.py`:
```python
import queue
import threading
from . import pipeline, store

class JobRunner:
    def __init__(self, deps_factory=pipeline.Deps):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self.busy = False
        self.deps_factory = deps_factory

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(); self._subs.append(q); return q

    def unsubscribe(self, q) -> None:
        if q in self._subs: self._subs.remove(q)

    def emit(self, ev: dict) -> None:
        for q in list(self._subs): q.put(ev)

    def submit(self, pid: str, kind: str, **kw) -> bool:
        with self._lock:
            if self.busy: return False
            self.busy = True
        threading.Thread(target=self._run, args=(pid, kind, kw), daemon=True).start()
        return True

    def _run(self, pid, kind, kw):
        deps = self.deps_factory()
        deps.progress = lambda msg, pct: self.emit({"pid": pid, "type": "progress", "msg": msg, "pct": round(pct, 3)})
        fn = {"segment": pipeline.run_segment, "images": pipeline.run_images, "render": pipeline.run_render}[kind]
        try:
            fn(pid, deps, **kw)
            self.emit({"pid": pid, "type": "done", "msg": kind, "pct": 1})
        except Exception as e:  # noqa: BLE001
            try:
                p = store.load(pid); p.job_error = str(e); store.save(p)
            except KeyError:
                pass
            self.emit({"pid": pid, "type": "error", "msg": str(e), "pct": 0})
        finally:
            self.busy = False

JOBS = JobRunner()
```

- [ ] **Step 4: Run** `pytest tests/test_pipeline.py -v` → 2 passed.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: per-scene pipeline stages and job runner"`

---

### Task 9: Startup checks + FastAPI

**Files:**
- Create: `studio/checks.py`, `studio/app.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `jobs.JOBS`, `store`, `ingest.extract_text`, `pipeline.invalidate`, `llm.build_image_prompt`
- Produces HTTP API (JSON = `Project` model):
  - `GET /api/health` → `{"checks":[{"name","ok","hint"}]}`
  - `GET /api/projects`, `GET /api/projects/{id}`
  - `POST /api/projects` multipart: `title`, `text?`, `file?`, `aspect`, `voice`, `captions`, `music`, `music_file?` → Project, then submits `segment`
  - `PUT /api/projects/{id}/scenes` body `list[Scene]` (only allowed in stage `scenes`/`images`; scenes whose text changed → `invalidate(…,"voice")`, whose visual/elements changed → rebuild `image_prompt` + `invalidate(…,"image")`; reassigns ids `01..`)
  - `PUT /api/projects/{id}/settings` body `Settings` (voice change invalidates all from `voice`)
  - `POST /api/projects/{id}/approve/scenes` → submit `images`
  - `POST /api/projects/{id}/scenes/{sid}/regenerate` body `{"image_prompt"?: str}` → submit `images` with `only=[sid]`
  - `POST /api/projects/{id}/render` → submit `render`
  - `GET /api/projects/{id}/events` SSE
  - `GET /api/projects/{id}/files/{path}` (image.png, final.mp4, voice.wav; path traversal rejected)
  - Busy → HTTP 409 `{"detail":"Đang có tác vụ khác chạy"}`

- [ ] **Step 1: Implement checks** `studio/checks.py`:
```python
import importlib.util
import shutil
import subprocess
from . import config

def run_checks() -> list[dict]:
    out = []
    def add(name, ok, hint): out.append({"name": name, "ok": bool(ok), "hint": "" if ok else hint})
    add("ffmpeg", shutil.which("ffmpeg"), "Cài ffmpeg: sudo apt install ffmpeg")
    add("node/npx", shutil.which("npx"), "Cài Node.js >= 18")
    add("remotion", (config.COMPOSER_DIR / "node_modules" / "remotion").exists(), "Chạy: cd composer && npm install")
    add("vieneu", importlib.util.find_spec("vieneu"), "Chạy: pip install -e '.[voice]'")
    add("GOOGLE_CLOUD_PROJECT", config.GCP_PROJECT, "Đặt biến môi trường GOOGLE_CLOUD_PROJECT=<project-id>")
    try:
        import google.auth
        google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        adc = True
    except Exception:  # noqa: BLE001
        adc = False
    add("ADC", adc, "Chạy: gcloud auth application-default login")
    return out
```

- [ ] **Step 2: Failing test** `tests/test_api.py`:
```python
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
    r.busy = True
    assert c.post(f"/api/projects/{pid}/render").status_code == 409
    r.busy = False
    assert c.get(f"/api/projects/{pid}/files/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)

def test_requires_input(monkeypatch):
    c, _ = client(monkeypatch)
    assert c.post("/api/projects", data={"title": "T"}).status_code == 400
```

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement** `studio/app.py`:
```python
import asyncio
import json
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

app = FastAPI(title="Whiteboard Studio")

def _get(pid):
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
    base = store.project_dir(pid).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "Không có file")
    return FileResponse(f)

_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
```

- [ ] **Step 5: Run** `pytest tests/test_api.py -v` → 3 passed.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: FastAPI endpoints, SSE progress, environment checks"`

---

### Task 10: Frontend (React + Vite)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/steps/NewProject.tsx`, `frontend/src/steps/ScenesReview.tsx`, `frontend/src/steps/ImagesReview.tsx`, `frontend/src/steps/RenderView.tsx`, `frontend/src/styles.css`

**Interfaces:**
- Consumes: HTTP API from Task 9.
- Produces: SPA; `App` picks step from `project.stage`: `input`→spinner while segmenting, `scenes`→ScenesReview, `images`→ImagesReview, `rendering|done`→RenderView.

- [ ] **Step 1: Config files**

`frontend/package.json`:
```json
{
  "name": "whiteboard-studio-ui", "private": true, "type": "module",
  "scripts": { "dev": "vite", "build": "tsc --noEmit && vite build" },
  "dependencies": { "react": "18.3.1", "react-dom": "18.3.1" },
  "devDependencies": { "@vitejs/plugin-react": "4.3.4", "vite": "5.4.11", "typescript": "5.6.3",
    "@types/react": "18.3.12", "@types/react-dom": "18.3.1" }
}
```
`frontend/vite.config.ts`:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], server: { proxy: { "/api": "http://127.0.0.1:8000" } } });
```
`frontend/tsconfig.json`:
```json
{ "compilerOptions": { "target": "ES2020", "module": "ESNext", "jsx": "react-jsx", "strict": true,
  "moduleResolution": "bundler", "skipLibCheck": true, "lib": ["ES2020", "DOM"] }, "include": ["src"] }
```
`frontend/index.html`:
```html
<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whiteboard Studio</title></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>
```
`frontend/src/main.tsx`:
```tsx
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
createRoot(document.getElementById("root")!).render(<App />);
```

- [ ] **Step 2: API client** `frontend/src/api.ts`:
```ts
export type Element = { label: string; say: string };
export type StepState = "pending" | "running" | "done" | "error";
export type Scene = { id: string; text: string; key_idea: string; visual_description: string; elements: Element[];
  image_prompt: string; status: Record<"image" | "voice" | "draw", StepState>; error: string | null; duration_ms: number | null };
export type Settings = { aspect: "16:9" | "9:16"; voice: string; captions: boolean; music: boolean; music_file: string | null };
export type Project = { id: string; title: string; created_at: string; settings: Settings; source_text: string;
  stage: "input" | "scenes" | "images" | "rendering" | "done"; scenes: Scene[]; final: string | null; job_error: string | null };
export type JobEvent = { pid: string; type: "progress" | "done" | "error"; msg: string; pct: number };

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}
export const api = {
  health: () => j<{ checks: { name: string; ok: boolean; hint: string }[] }>(fetch("/api/health")),
  list: () => j<Project[]>(fetch("/api/projects")),
  get: (id: string) => j<Project>(fetch(`/api/projects/${id}`)),
  create: (fd: FormData) => j<Project>(fetch("/api/projects", { method: "POST", body: fd })),
  saveScenes: (id: string, scenes: Scene[]) => j<Project>(fetch(`/api/projects/${id}/scenes`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(scenes) })),
  approveScenes: (id: string) => j(fetch(`/api/projects/${id}/approve/scenes`, { method: "POST" })),
  regenerate: (id: string, sid: string, image_prompt?: string) => j(fetch(`/api/projects/${id}/scenes/${sid}/regenerate`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_prompt }) })),
  render: (id: string) => j(fetch(`/api/projects/${id}/render`, { method: "POST" })),
  file: (id: string, path: string, bust = "") => `/api/projects/${id}/files/${path}${bust ? `?v=${bust}` : ""}`,
  events: (id: string, on: (e: JobEvent) => void) => {
    const es = new EventSource(`/api/projects/${id}/events`);
    es.onmessage = (m) => on(JSON.parse(m.data));
    return () => es.close();
  },
};
```

- [ ] **Step 3: App shell** `frontend/src/App.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { api, JobEvent, Project } from "./api";
import NewProject from "./steps/NewProject";
import ScenesReview from "./steps/ScenesReview";
import ImagesReview from "./steps/ImagesReview";
import RenderView from "./steps/RenderView";

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [list, setList] = useState<Project[]>([]);
  const [ev, setEv] = useState<JobEvent | null>(null);
  const [checks, setChecks] = useState<{ name: string; ok: boolean; hint: string }[]>([]);

  useEffect(() => { api.list().then(setList); api.health().then((h) => setChecks(h.checks)); }, []);
  const reload = useCallback(async () => { if (project) setProject(await api.get(project.id)); }, [project?.id]);

  useEffect(() => {
    if (!project) return;
    return api.events(project.id, (e) => { setEv(e); if (e.type !== "progress") { reload(); } });
  }, [project?.id]);

  // also refresh periodically while a scene step is running so thumbnails/status update
  useEffect(() => {
    if (!ev || ev.type !== "progress") return;
    const t = setTimeout(reload, 1500); return () => clearTimeout(t);
  }, [ev]);

  const bad = checks.filter((c) => !c.ok);
  return (
    <div className="app">
      <header>
        <h1 onClick={() => { setProject(null); api.list().then(setList); }}>Whiteboard Studio</h1>
        {project && <span className="muted">{project.title} · {project.settings.aspect}</span>}
      </header>
      {bad.length > 0 && <div className="warn">{bad.map((c) => <div key={c.name}>⚠ {c.name}: {c.hint}</div>)}</div>}
      {ev && ev.type === "progress" && <div className="progress"><div style={{ width: `${ev.pct * 100}%` }} /><span>{ev.msg}</span></div>}
      {ev && ev.type === "error" && <div className="error">Lỗi: {ev.msg}</div>}
      {!project && <NewProject list={list} onOpen={setProject} />}
      {project?.stage === "input" && <p className="muted">Gemini đang chia cảnh…</p>}
      {project?.stage === "scenes" && <ScenesReview project={project} onChange={setProject} />}
      {project?.stage === "images" && <ImagesReview project={project} onChange={setProject} reload={reload} />}
      {(project?.stage === "rendering" || project?.stage === "done") && <RenderView project={project} onBack={reload} />}
    </div>
  );
}
```

- [ ] **Step 4: Steps**

`frontend/src/steps/NewProject.tsx`:
```tsx
import { useState } from "react";
import { api, Project } from "../api";

export default function NewProject({ list, onOpen }: { list: Project[]; onOpen: (p: Project) => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setErr(""); setBusy(true);
    const fd = new FormData(e.currentTarget);
    fd.set("captions", String(fd.get("captions") === "on"));
    fd.set("music", String(fd.get("music") === "on"));
    for (const k of ["file", "music_file"]) { const f = fd.get(k) as File | null; if (f && !f.name) fd.delete(k); }
    try { onOpen(await api.create(fd)); } catch (x) { setErr(String((x as Error).message)); } finally { setBusy(false); }
  }
  return (
    <div className="grid2">
      <form className="card" onSubmit={submit}>
        <h2>Dự án mới</h2>
        <label>Tên dự án<input name="title" placeholder="VD: Lạm phát là gì?" /></label>
        <label>Kịch bản<textarea name="text" rows={10} placeholder="Dán kịch bản vào đây…" /></label>
        <label>…hoặc tải file (.txt .docx .srt .pdf)<input type="file" name="file" accept=".txt,.docx,.srt,.pdf" /></label>
        <div className="row">
          <label>Tỉ lệ<select name="aspect"><option value="16:9">16:9 YouTube</option><option value="9:16">9:16 TikTok/Shorts</option></select></label>
          <label>Giọng VieNeu<input name="voice" defaultValue="Hải Đăng" /></label>
        </div>
        <div className="row">
          <label className="check"><input type="checkbox" name="captions" defaultChecked /> Phụ đề karaoke</label>
          <label className="check"><input type="checkbox" name="music" /> Nhạc nền</label>
          <input type="file" name="music_file" accept="audio/*" />
        </div>
        {err && <div className="error">{err}</div>}
        <button disabled={busy}>{busy ? "Đang tạo…" : "Tạo & chia cảnh"}</button>
      </form>
      <div className="card">
        <h2>Dự án gần đây</h2>
        {list.length === 0 && <p className="muted">Chưa có dự án.</p>}
        {list.map((p) => (
          <div key={p.id} className="listItem" onClick={() => onOpen(p)}>
            <b>{p.title}</b> <span className="muted">{p.settings.aspect} · {p.stage} · {p.scenes.length} cảnh</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

`frontend/src/steps/ScenesReview.tsx`:
```tsx
import { useState } from "react";
import { api, Project, Scene } from "../api";

const blank = (): Scene => ({ id: "new", text: "", key_idea: "", visual_description: "", elements: [], image_prompt: "",
  status: { image: "pending", voice: "pending", draw: "pending" }, error: null, duration_ms: null });

export default function ScenesReview({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [scenes, setScenes] = useState<Scene[]>(project.scenes);
  const [msg, setMsg] = useState("");
  const set = (i: number, patch: Partial<Scene>) => setScenes(scenes.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const merge = (i: number) => {
    const a = scenes[i], b = scenes[i + 1];
    const m = { ...a, id: "new", text: `${a.text} ${b.text}`, elements: [...a.elements, ...b.elements],
      visual_description: `${a.visual_description}; ${b.visual_description}` };
    setScenes([...scenes.slice(0, i), m, ...scenes.slice(i + 2)]);
  };
  const split = (i: number) => {
    const s = scenes[i]; const cut = s.text.indexOf(". ", s.text.length / 2);
    if (cut < 0) return;
    setScenes([...scenes.slice(0, i), { ...s, id: "new", text: s.text.slice(0, cut + 1) },
      { ...blank(), text: s.text.slice(cut + 2), visual_description: s.visual_description, elements: s.elements }, ...scenes.slice(i + 1)]);
  };
  async function save(approve: boolean) {
    try {
      const p = await api.saveScenes(project.id, scenes);
      if (approve) { await api.approveScenes(project.id); setMsg("Đang tạo ảnh…"); }
      onChange(p);
    } catch (e) { setMsg(String((e as Error).message)); }
  }
  const words = (t: string) => t.split(/\s+/).filter(Boolean).length;
  return (
    <div>
      <h2>Bước 1 · Duyệt chia cảnh ({scenes.length} cảnh)</h2>
      {scenes.map((s, i) => (
        <div className="card scene" key={i}>
          <div className="row between"><b>Cảnh {i + 1}</b><span className="muted">~{Math.round(words(s.text) / 4)} giây</span></div>
          <label>Lời đọc<textarea rows={4} value={s.text} onChange={(e) => set(i, { text: e.target.value })} /></label>
          <label>Mô tả hình (EN)<textarea rows={2} value={s.visual_description} onChange={(e) => set(i, { visual_description: e.target.value })} /></label>
          <label>Đối tượng vẽ — mỗi dòng: <code>label | cụm từ kích hoạt</code>
            <textarea rows={3} value={s.elements.map((e) => `${e.label} | ${e.say}`).join("\n")}
              onChange={(e) => set(i, { elements: e.target.value.split("\n").filter((l) => l.trim()).map((l) => {
                const [label, say = ""] = l.split("|").map((x) => x.trim()); return { label, say }; }) })} />
          </label>
          <div className="row">
            {i < scenes.length - 1 && <button type="button" onClick={() => merge(i)}>Gộp với cảnh sau</button>}
            <button type="button" onClick={() => split(i)}>Tách đôi</button>
            <button type="button" className="danger" onClick={() => setScenes(scenes.filter((_, k) => k !== i))}>Xoá</button>
          </div>
        </div>
      ))}
      <div className="row sticky">
        <button type="button" onClick={() => setScenes([...scenes, blank()])}>+ Thêm cảnh</button>
        <button type="button" onClick={() => save(false)}>Lưu</button>
        <button type="button" className="primary" onClick={() => save(true)}>Duyệt → Tạo ảnh</button>
        <span className="muted">{msg}</span>
      </div>
    </div>
  );
}
```

`frontend/src/steps/ImagesReview.tsx`:
```tsx
import { useState } from "react";
import { api, Project } from "../api";

export default function ImagesReview({ project, onChange, reload }: { project: Project; onChange: (p: Project) => void; reload: () => void }) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const run = async (f: () => Promise<unknown>) => { setErr(""); try { await f(); reload(); } catch (e) { setErr(String((e as Error).message)); } };
  const allDone = project.scenes.every((s) => s.status.image === "done");
  return (
    <div>
      <h2>Bước 2 · Duyệt ảnh</h2>
      {err && <div className="error">{err}</div>}
      {project.job_error && <div className="error">{project.job_error}</div>}
      <div className={`thumbs ${project.settings.aspect === "9:16" ? "portrait" : ""}`}>
        {project.scenes.map((s) => (
          <div className="card" key={s.id}>
            <b>Cảnh {s.id}</b> <span className={`badge ${s.status.image}`}>{s.status.image}</span>
            {s.status.image === "done"
              ? <img src={api.file(project.id, `scenes/${s.id}/image.png`, project.created_at + s.image_prompt.length + s.status.image)} />
              : <div className="placeholder">{s.status.image === "running" ? "Đang vẽ…" : s.error ?? "Chưa có ảnh"}</div>}
            <p className="small">{s.text}</p>
            <details><summary>Sửa prompt</summary>
              <textarea rows={5} value={prompts[s.id] ?? s.image_prompt} onChange={(e) => setPrompts({ ...prompts, [s.id]: e.target.value })} />
            </details>
            <button onClick={() => run(() => api.regenerate(project.id, s.id, prompts[s.id]))}>Tạo lại ảnh</button>
          </div>
        ))}
      </div>
      <div className="row sticky">
        <button onClick={() => onChange({ ...project, stage: "scenes" })}>← Sửa cảnh</button>
        <button onClick={() => run(() => api.approveScenes(project.id))}>Tạo các ảnh còn thiếu/lỗi</button>
        <button className="primary" disabled={!allDone} onClick={() => run(() => api.render(project.id))}>Duyệt → Lồng tiếng & render</button>
      </div>
    </div>
  );
}
```

`frontend/src/steps/RenderView.tsx`:
```tsx
import { api, Project } from "../api";

export default function RenderView({ project, onBack }: { project: Project; onBack: () => void }) {
  return (
    <div>
      <h2>Bước 3 · {project.stage === "done" ? "Hoàn tất" : "Đang render"}</h2>
      <table className="status">
        <thead><tr><th>Cảnh</th><th>Giọng</th><th>Vẽ</th><th>Thời lượng</th><th>Lỗi</th></tr></thead>
        <tbody>{project.scenes.map((s) => (
          <tr key={s.id}><td>{s.id}</td><td className={s.status.voice}>{s.status.voice}</td><td className={s.status.draw}>{s.status.draw}</td>
            <td>{s.duration_ms ? (s.duration_ms / 1000).toFixed(1) + "s" : ""}</td><td className="small">{s.error}</td></tr>))}
        </tbody>
      </table>
      {project.stage === "done" && project.final && (
        <div className="card">
          <video controls src={api.file(project.id, project.final, project.created_at + Date.now())} className={project.settings.aspect === "9:16" ? "portrait" : ""} />
          <a className="primary button" href={api.file(project.id, project.final)} download={`${project.title}.mp4`}>Tải MP4</a>
        </div>
      )}
      <button onClick={onBack}>Làm mới</button>
    </div>
  );
}
```

`frontend/src/styles.css`:
```css
:root { --paper:#F5EBD7; --ink:#2f2f2f; --muted:#7a7266; --accent:#d9622b; --ok:#3f8f5a; --err:#c0392b; font-family: system-ui, "Be Vietnam Pro", sans-serif; color: var(--ink); }
body { margin:0; background: var(--paper); }
.app { max-width: 1200px; margin: 0 auto; padding: 16px; }
header { display:flex; gap:16px; align-items:baseline; } header h1 { cursor:pointer; margin: 8px 0; }
.card { background:#fffaf0; border:1px solid #e3d6bb; border-radius:12px; padding:16px; margin-bottom:12px; }
label { display:block; margin:8px 0; font-weight:600; font-size:14px; }
input, textarea, select { width:100%; box-sizing:border-box; padding:8px; border:1px solid #d8c9aa; border-radius:8px; font: inherit; font-weight:400; background:#fff; }
input[type=checkbox] { width:auto; } .check { display:flex; gap:6px; align-items:center; }
button, .button { padding:8px 14px; border-radius:8px; border:1px solid #cbb994; background:#fff; cursor:pointer; text-decoration:none; color:inherit; display:inline-block; }
.primary { background: var(--accent); color:#fff; border-color: var(--accent); } .danger { color: var(--err); }
button:disabled { opacity:.5; cursor:not-allowed; }
.row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; } .between { justify-content:space-between; }
.grid2 { display:grid; grid-template-columns: 2fr 1fr; gap:16px; } @media (max-width:800px){ .grid2 { grid-template-columns:1fr; } }
.sticky { position:sticky; bottom:0; background:var(--paper); padding:10px 0; border-top:1px solid #e3d6bb; }
.muted { color: var(--muted); } .small { font-size: 13px; }
.error { color: var(--err); background:#fbe9e7; padding:8px 12px; border-radius:8px; margin:8px 0; }
.warn { background:#fff3cd; padding:8px 12px; border-radius:8px; margin:8px 0; font-size:14px; }
.progress { position:relative; height:26px; background:#eadfc8; border-radius:13px; overflow:hidden; margin:8px 0; }
.progress div { position:absolute; inset:0 auto 0 0; background:#e9a77f; transition: width .4s; } .progress span { position:relative; padding-left:12px; line-height:26px; font-size:13px; }
.thumbs { display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap:12px; } .thumbs.portrait { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.thumbs img, .placeholder { width:100%; border-radius:8px; background:#eee3cc; } .placeholder { aspect-ratio:16/9; display:flex; align-items:center; justify-content:center; color:var(--muted); }
.badge { font-size:12px; padding:2px 8px; border-radius:10px; background:#eee; } .badge.done, td.done { color: var(--ok); } .badge.error, td.error { color: var(--err); }
.listItem { padding:8px; border-radius:8px; cursor:pointer; } .listItem:hover { background:#f3e8d2; }
video { width:100%; border-radius:8px; } video.portrait { max-height:80vh; width:auto; display:block; margin:0 auto; }
table.status { width:100%; border-collapse: collapse; margin-bottom:12px; } table.status td, table.status th { border-bottom:1px solid #e3d6bb; padding:6px; text-align:left; }
```

- [ ] **Step 5: Build** `cd frontend && npm install && npm run build && cd ..` → `dist/` created, no TS errors.
- [ ] **Step 6: Manual check** `uvicorn studio.app:app --port 8000` + `cd frontend && npm run dev` → open http://localhost:5173, create project with text, verify progress bar and scene list appear.
- [ ] **Step 7: Commit** `git add -A && git commit -m "feat: React UI with scene and image review gates"`

---

### Task 11: E2E test with real draw + Remotion, Makefile, README

**Files:**
- Create: `tests/test_e2e.py`, `Makefile`, `README.md`

**Interfaces:**
- Consumes: everything. Mocks only Gemini (segment + image) and VieNeu.

- [ ] **Step 1: Failing test** `tests/test_e2e.py`:
```python
import json
import shutil
import subprocess
import pytest
import cv2
import numpy as np
import soundfile as sf
from studio import config, pipeline, store
from studio.models import Element, Scene, Settings
from tests.test_annotate import make_scene

pytestmark = pytest.mark.skipif(not (config.COMPOSER_DIR / "node_modules").exists(), reason="composer not installed")

def seg(text, aspect):
    return [Scene(id=f"{i:02d}", text=t, visual_description="v", elements=[Element(label="a", say=t.split()[0]),
            Element(label="b", say=t.split()[-1].strip("."))], image_prompt="p") for i, t in enumerate(["Giá cả tăng nhanh.", "Tiền mất giá."], 1)]

def img(prompt, aspect, out):
    make_scene(out); return out

def synth(text, voice, out_wav):
    rate = 24000
    sf.write(out_wav, 0.05 * np.sin(np.linspace(0, 440 * 2 * np.pi * 2, rate * 2)), rate)
    words = [{"text": w, "start_ms": 300 + i * 300, "end_ms": 550 + i * 300} for i, w in enumerate(text.split())]
    out_wav.with_name("words.json").write_text(json.dumps(words, ensure_ascii=False)); return words

def test_e2e_two_scenes():
    p = store.create_project("e2e", Settings(aspect="16:9", captions=True), "x")
    d = pipeline.Deps(segment=seg, gen_image=img, synth=synth)
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d); pipeline.run_render(p.id, d)
    out = store.project_dir(p.id) / "final.mp4"
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(out)]))
    kinds = {s["codec_type"] for s in probe["streams"]}
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert kinds == {"video", "audio"}
    assert (v["width"], v["height"]) == (1920, 1080)
    assert abs(float(probe["format"]["duration"]) - 4.0) < 0.3
```

- [ ] **Step 2: Run** `pytest tests/test_e2e.py -v -s` → fix integration issues until PASS (expect 1–3 min). Typical fixes: `staticFile` needs paths without leading slash (already); remotion may need `--log=verbose` to debug.

- [ ] **Step 3: Makefile**
```makefile
.PHONY: setup dev test build
setup:
	python3 -m venv .venv && .venv/bin/pip install -e '.[dev,voice]'
	cd composer && npm install
	cd frontend && npm install
dev:
	.venv/bin/uvicorn studio.app:app --port 8000 --reload & cd frontend && npm run dev
build:
	cd frontend && npm run build
run: build
	.venv/bin/uvicorn studio.app:app --port 8000
test:
	.venv/bin/pytest -v
```

- [ ] **Step 4: README.md** (Vietnamese): prerequisites (Python ≥3.10, Node ≥18, ffmpeg, gcloud), `gcloud auth application-default login`, `export GOOGLE_CLOUD_PROJECT=…`, optional `GOOGLE_CLOUD_LOCATION`, `GEMINI_TEXT_MODEL`, `GEMINI_IMAGE_MODEL`, `VIENEU_MODE`; `make setup && make run` → http://localhost:8000; flow description; credits to geeklee (MIT) and vansyson (license file) for vendored code.

- [ ] **Step 5: Full test run** `make test` → all pass. Commit `git add -A && git commit -m "test: e2e pipeline; docs: README and Makefile"`

- [ ] **Step 6: Real smoke** (with ADC + vieneu): create a 3-sentence project in UI, approve both gates, confirm final MP4 plays with voice, captions, drawing synced.

---

## Self-review notes
- Spec coverage: ingest (T2), Gemini ADC segment/image (T3), VieNeu (T4), annotation timing (T5), geeklee draw (T6), Remotion + captions + music ducking (T7), per-scene cache/errors (T8), gates + SSE + checks (T9), UI (T10), E2E + ffprobe (T11).
- Python is 3.10 on this machine → `requires-python >=3.10` (spec said 3.11; harmless relaxation).
- `draw.render_clip` signature finalized as `(image, annotation, out, fps=30)`; used identically in T8/T11.
