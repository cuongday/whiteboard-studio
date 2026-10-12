"""Drawing hand for the whiteboard renderer: a plain marker, or the user's text printed on the barrel.

Adapted from vansyson/srt-whiteboard-animation scripts/brand_hand.py (MIT, see vendor/LICENSE-vansyson).
"""
import hashlib
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config

VENDOR = Path(__file__).resolve().parent / "vendor"
CLEAN_HAND = VENDOR / "drawing-hand-clean.png"
FONT = VENDOR / "fonts" / "BeVietnamPro-ExtraBold.ttf"
CACHE = config.ROOT / ".cache" / "hands"
DEFAULT_COLOR = "#1f1f1f"
MAX_TEXT = 40
_LOCK = threading.Lock()   # scenes draw in parallel and may all ask for a new branded hand

def _barrel_mask(rgba: np.ndarray) -> np.ndarray:
    """The visible white part of the marker barrel (largest near-white blob)."""
    hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 2] > 215) & (hsv[:, :, 1] < 40) & (rgba[:, :, 3] > 200)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(white)
    if n < 2:
        raise RuntimeError("Không tìm thấy thân bút trong ảnh bàn tay")
    return (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)

def _brand(text: str, color: str, out: Path) -> Path:
    rgba = cv2.imread(str(CLEAN_HAND), cv2.IMREAD_UNCHANGED)
    mask = _barrel_mask(rgba)
    pts = np.argwhere(mask > 0)[:, ::-1].astype(np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
    length, thick = max(w, h), min(w, h)
    axis = ang if w >= h else ang + 90          # long-axis direction (image coords, y down)
    size = int(thick * 0.62)
    font = ImageFont.truetype(str(FONT), size)
    measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = measure.textlength(text, font=font)
    while tw > length * 0.8 and size > 10:
        size -= 2
        font = ImageFont.truetype(str(FONT), size)
        tw = measure.textlength(text, font=font)
    rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    pad = size
    layer = Image.new("RGBA", (int(tw) + 2 * pad, size * 2 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((pad, pad + size * 0.35), text, font=font, fill=(*rgb, 255))
    layer = layer.rotate(-axis, expand=True, resample=Image.BICUBIC)
    canvas = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), (0, 0, 0, 0))
    canvas.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)
    txt = np.asarray(canvas).astype(np.float32)
    inner = cv2.erode(mask, np.ones((7, 7), np.uint8)).astype(np.float32)
    a = txt[:, :, 3:4] / 255.0 * inner[:, :, None]       # keep text inside the barrel
    img = rgba.astype(np.float32)
    img[:, :, :3] = img[:, :, :3] * (1 - a) + txt[:, :, 2::-1] * a
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    cv2.imwrite(str(tmp), img.astype(np.uint8))
    tmp.replace(out)
    return out

def normalize(text: str | None, color: str | None) -> tuple[str, str]:
    text = " ".join((text or "").split())[:MAX_TEXT]
    color = (color or DEFAULT_COLOR).strip()
    if len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
        color = DEFAULT_COLOR
    return text, color.lower()

def hand_png(text: str | None, color: str | None = None) -> Path:
    """Hand image for the renderer: the clean marker, or a cached branded copy."""
    text, color = normalize(text, color)
    if not text:
        return CLEAN_HAND
    key = hashlib.sha1(f"{text}\0{color}".encode()).hexdigest()[:16]
    out = CACHE / f"hand-{key}.png"
    with _LOCK:
        return out if out.exists() else _brand(text, color, out)
