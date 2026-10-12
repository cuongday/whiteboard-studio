import json

import cv2
import subprocess
import sys
from pathlib import Path

RENDERER = Path(__file__).resolve().parent / "vendor" / "render_stream_whiteboard.py"

def _image_size(image: Path) -> tuple[int, int]:
    img = cv2.imread(str(image))
    if img is None:
        raise RuntimeError(f"Không đọc được ảnh: {image}")
    return img.shape[:2]


def render_clip(image: Path, annotation: dict, out: Path, fps: int = 30, hand: Path | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ann_path = out.with_name("annotation.json")
    ann_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    h, w = _image_size(image)
    if hand is None:
        from .hand import CLEAN_HAND
        hand = CLEAN_HAND
    cmd = [sys.executable, str(RENDERER), str(image), str(ann_path), str(out), str(hand),
           "--fps", str(fps), "--total-ms", str(annotation["sceneDurationMs"]),
           "--cap-long-edge", str(max(h, w))]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("Lỗi vẽ cảnh: " + (r.stderr or r.stdout)[-800:])
    return out
