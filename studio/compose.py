import json
import os
import math
import re
import subprocess
from pathlib import Path
from . import config, proc, store, versions
from .models import Project

def build_props(p: Project, vid: str) -> dict:
    w, h = config.ASPECTS[p.settings.aspect]
    v = versions.get(p, vid)
    scenes = []
    for s in p.scenes:
        vs = v.scenes[s.id]
        d = versions.vscene_dir(p.id, vid, s.id)
        words = json.loads((d / "words.json").read_text(encoding="utf-8")) if (d / "words.json").exists() else []
        base = f"versions/{vid}/scenes/{s.id}"
        scenes.append({"clip": f"{base}/clip.mp4", "audio": f"{base}/voice.wav",
                       "durationInFrames": math.ceil((vs.duration_ms or 0) * config.FPS / 1000), "words": words})
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

def render_final(p: Project, vid: str, on_progress=None) -> Path:
    """Final video with the engine chosen in project settings (ffmpeg by default)."""
    if p.settings.composer == "ffmpeg":
        from . import compose_ffmpeg
        return compose_ffmpeg.render_final(p, vid, on_progress=on_progress)
    return render_remotion(p, vid, on_progress=on_progress)

def render_remotion(p: Project, vid: str, on_progress=None) -> Path:
    pdir = store.project_dir(p.id)
    vd = versions.vdir(p.id, vid)
    vd.mkdir(parents=True, exist_ok=True)
    props_file = vd / "props.json"
    props_file.write_text(json.dumps(build_props(p, vid), ensure_ascii=False), encoding="utf-8")
    out = vd / "final.mp4"
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
    pr = proc.popen(cmd, cwd=config.COMPOSER_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail: list[str] = []
    for line in pr.stdout:
        tail = (tail + [line])[-40:]
        m = _PROG.search(line)
        if on_progress and m and "Rendered" in line:
            on_progress(int(m.group(1)) / max(1, int(m.group(2))))
    try:
        return pr.wait() == 0, tail
    finally:
        proc.done(pr)

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

def make_preview(clip: Path, wav: Path, out: Path) -> Path:
    """Scene preview for the editor: whiteboard clip + narration, video stream copied (~1 s)."""
    r = proc.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-i", str(wav),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(out)])
    if r.returncode != 0:
        raise RuntimeError("Lỗi tạo bản xem thử: " + r.stderr[-400:])
    return out
