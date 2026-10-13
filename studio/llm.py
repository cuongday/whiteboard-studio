import hashlib
import shutil
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
            code = getattr(e, "code", None) or 0
            if (code == 429 or code >= 500) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise LLMError(f"Gemini lỗi: {e}") from e

def build_image_prompt(scene: Scene) -> str:
    objs = ", ".join(e.label for e in scene.elements)
    return f"{STYLE}\nScene: {scene.visual_description}\nDistinct objects to draw: {objs}."

def segment_script(text: str, aspect: str, client=None, model: str | None = None) -> list[Scene]:
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
        resp = _call(client, model=model or config.TEXT_MODEL, contents=prompt, config=cfg)
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

IMAGE_CACHE = config.ROOT / ".cache" / "images"

def generate_image(prompt: str, aspect: str, out: Path, client=None, model: str | None = None,
                   fresh: bool = False) -> Path:
    """fresh=False reuses an earlier image of the same (prompt, model, aspect) instead of paying again."""
    model = model or config.IMAGE_MODEL
    key = hashlib.sha256(json.dumps([prompt, model, aspect]).encode()).hexdigest()[:24]
    cached = IMAGE_CACHE / f"{key}.png"
    if not fresh and cached.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out)
        return out
    _generate_image(prompt, aspect, out, client, model)
    IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, cached)
    return out

def _generate_image(prompt: str, aspect: str, out: Path, client, model: str) -> Path:
    client = client or get_client()
    cfg = types.GenerateContentConfig(response_modalities=["IMAGE"],
                                      image_config=types.ImageConfig(aspect_ratio=aspect))
    resp = _call(client, model=model, contents=prompt, config=cfg)
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(part.inline_data.data)
                return out
    raise LLMError("Gemini không trả về ảnh")
