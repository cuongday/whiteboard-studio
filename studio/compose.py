import json
import os
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
# Chrome/asset-proxy hiccups that succeed on a plain retry (e.g. ERR_NETWORK_CHANGED when
# docker/VPN interfaces flap, transient fetch failures under memory pressure)
_TRANSIENT = ("ERR_NETWORK_CHANGED", "Failed to fetch", "ERR_CONNECTION_RESET", "Target closed", "ECONNRESET")
RENDER_ATTEMPTS = int(os.environ.get("STUDIO_RENDER_ATTEMPTS", "2"))
RENDER_CONCURRENCY = os.environ.get("STUDIO_RENDER_CONCURRENCY", "50%")
# frame cache of the OffthreadVideo server; Remotion's default is half the free RAM
OFFTHREAD_CACHE_BYTES = int(os.environ.get("STUDIO_OFFTHREAD_CACHE_MB", "1024")) * 1024 * 1024

def render_final(p: Project, on_progress=None) -> Path:
    pdir = store.project_dir(p.id)
    props_file = pdir / "props.json"
    props_file.write_text(json.dumps(build_props(p), ensure_ascii=False), encoding="utf-8")
    out = pdir / "final.mp4"
    cmd = ["npx", "remotion", "render", "src/index.ts", "FinalVideo", str(out),
           f"--props={props_file}", f"--public-dir={pdir}", f"--concurrency={RENDER_CONCURRENCY}",
           f"--offthreadvideo-cache-size-in-bytes={OFFTHREAD_CACHE_BYTES}", "--timeout=60000"]
    attempts = max(1, RENDER_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        ok, tail = _run_remotion(cmd, on_progress)
        if ok and out.exists():
            return out
        log = "".join(tail)
        if attempt == attempts or not any(t in log for t in _TRANSIENT):
            raise RuntimeError(_explain(log) + "\n" + _summarize(tail))
    raise AssertionError("unreachable")

def _run_remotion(cmd, on_progress) -> tuple[bool, list[str]]:
    proc = subprocess.Popen(cmd, cwd=config.COMPOSER_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail: list[str] = []
    for line in proc.stdout:
        tail = (tail + [line])[-40:]
        m = _PROG.search(line)
        if on_progress and m and "Rendered" in line:
            on_progress(int(m.group(1)) / max(1, int(m.group(2))))
    return proc.wait() == 0, tail

def _summarize(tail: list[str]) -> str:
    """Drop the repetitive "Rendered x/y" progress spam so the real error is readable."""
    keep = [l.rstrip() for l in tail if l.strip() and not l.lstrip().startswith("Rendered ")]
    return "\n".join(keep[-15:])

def _explain(log: str) -> str:
    if any(t in log for t in _TRANSIENT):
        return ("Remotion lỗi: trình duyệt render mất kết nối tới file cảnh (lỗi mạng/bộ nhớ tạm thời, "
                f"đã thử lại {RENDER_ATTEMPTS} lần). Thường do máy thiếu RAM hoặc card mạng thay đổi; "
                "hãy bấm render lại.")
    return "Remotion lỗi:"
