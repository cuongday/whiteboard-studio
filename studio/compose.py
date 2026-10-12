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
