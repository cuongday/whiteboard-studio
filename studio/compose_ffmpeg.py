"""Fast final-video composer using ffmpeg only (alternative to the Remotion composer).

Same output contract as compose.render_final: versions/<vid>/final.mp4 made of the scene clips,
narration, optional karaoke captions (ASS, burned in) and optional ducked background music.
The scene clips are already rendered frames, so only captions need drawing: one libx264 pass.
"""
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import config, proc as procs, store, versions
from .models import Project

FONT_DIR = Path(__file__).resolve().parent / "vendor" / "fonts"
FONT_NAME = "Be Vietnam Pro ExtraBold"
SAMPLE_RATE = 48000
PRESET = os.environ.get("STUDIO_FFMPEG_PRESET", "veryfast")
CRF = os.environ.get("STUDIO_FFMPEG_CRF", "20")
MUSIC_VOL, DUCKED_VOL, DUCK_PAD_MS = 0.3, 0.08, 270      # same levels as composer/src/FinalVideo.tsx

def _ass_time(ms: float) -> str:
    cs = max(0, int(round(ms / 10)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def _ass_escape(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")

def _lines(words: list[dict]) -> list[list[dict]]:
    """Max 7 words per caption line, break after sentence punctuation (as Captions.tsx)."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 7 or re.search(r"[.!?…]$", w["text"]):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out

def build_ass(scenes: list[tuple[float, list[dict]]], width: int, height: int) -> str:
    """scenes = [(offset_ms, words)]; karaoke line: spoken words turn yellow, boxed dark background."""
    portrait = height > width
    # ASS font size is the line height; ~1.3x the CSS px size used by Captions.tsx looks the same
    size = 70 if portrait else 60
    margin = 260 if portrait else 70
    # BorderStyle 3 = opaque box; colours are &HAABBGGRR (AA: 00 opaque … FF transparent)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Box,{FONT_NAME},{size},&HFF000000,&HFF000000,&H48282828,&HFF000000,0,0,0,0,100,100,0,0,3,14,0,2,{int(width * 0.07)},{int(width * 0.07)},{margin},1
Style: Cap,{FONT_NAME},{size},&H0057C8FF,&H00FFFFFF,&HFF000000,&HFF000000,0,0,0,0,100,100,0,0,1,0,0,2,{int(width * 0.07)},{int(width * 0.07)},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for offset, words in scenes:
        lines = _lines(words)
        for li, line in enumerate(lines):
            start = offset + line[0]["start_ms"] - 100
            end = offset + line[-1]["end_ms"] + 300
            # Captions.tsx shows ONE line at a time; never let a line's 300 ms tail overlap the next
            # line (libass would stack both). Next line takes over at its own start time.
            if li + 1 < len(lines):
                end = min(end, offset + lines[li + 1][0]["start_ms"] - 100)
            end = max(end, start + 10)
            # ASS karaoke: "{\\kN}word" = word is unsung (white) until the running clock reaches it,
            # then sung (yellow); N = this word's own duration. Lead-in gap is an empty syllable.
            parts = [f"{{\\k{max(0, round((offset + line[0]['start_ms'] - start) / 10))}}}"]
            for j, w in enumerate(line):
                nxt = line[j + 1]["start_ms"] if j + 1 < len(line) else w["end_ms"]
                parts.append(f"{{\\k{max(1, round((nxt - w['start_ms']) / 10))}}}{_ass_escape(w['text'])} ")
            plain = " ".join(_ass_escape(w["text"]) for w in line)
            # layer 0: one dark box behind the whole line (text itself invisible);
            # layer 1: karaoke text without a box (per-word boxes would overlap into stripes)
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Box,,0,0,0,,{plain}")
            events.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{''.join(parts).rstrip()}")
    return head + "\n".join(events) + "\n"

def _duck_expr(spans_ms: list[tuple[float, float]]) -> str:
    if not spans_ms:
        return str(MUSIC_VOL)
    cond = "+".join(f"between(t,{(a - DUCK_PAD_MS) / 1000:.3f},{(b + DUCK_PAD_MS) / 1000:.3f})" for a, b in spans_ms)
    return f"if(gt({cond},0),{DUCKED_VOL},{MUSIC_VOL})"

_TIME = re.compile(r"out_time_ms=(\d+)")

def render_final(p: Project, vid: str, on_progress=None) -> Path:
    v = versions.get(p, vid)
    pdir = store.project_dir(p.id)
    vd = versions.vdir(p.id, vid); vd.mkdir(parents=True, exist_ok=True)
    w, h = config.ASPECTS[p.settings.aspect]
    fps = config.FPS
    out = vd / "final.mp4"
    tmp_out = vd / "final.ffmpeg.tmp.mp4"

    inputs: list[str] = []
    vf, af = [], []
    cap_scenes, spans = [], []
    offset = 0.0
    for i, s in enumerate(p.scenes):
        vs = v.scenes[s.id]
        d = versions.vscene_dir(p.id, vid, s.id)
        frames = math.ceil((vs.duration_ms or 0) * fps / 1000)
        dur = frames / fps
        inputs += ["-i", str(d / "clip.mp4"), "-i", str(d / "voice.wav")]
        # pad/trim every scene to exactly its frame count so audio and video stay in lock-step
        vf.append(f"[{2 * i}:v]fps={fps},scale={w}:{h},setsar=1,format=yuv420p,"
                  f"tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
        af.append(f"[{2 * i + 1}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                  f"apad,atrim=duration={dur:.3f},asetpts=PTS-STARTPTS[a{i}]")
        words = json.loads((d / "words.json").read_text(encoding="utf-8")) if (d / "words.json").exists() else []
        cap_scenes.append((offset * 1000, words))
        if words:
            spans.append((offset * 1000 + words[0]["start_ms"], offset * 1000 + words[-1]["end_ms"]))
        offset += dur
    n = len(p.scenes)
    total_ms = offset * 1000
    graph = vf + af
    graph.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vcat][acat]")

    vlast = "vcat"
    with tempfile.TemporaryDirectory(prefix="wbs-ass-") as td:
        if p.settings.captions:
            ass = Path(td) / "captions.ass"
            ass.write_text(build_ass(cap_scenes, w, h), encoding="utf-8")
            graph.append(f"[vcat]ass=filename={ass}:fontsdir={FONT_DIR}[vout]")
            vlast = "vout"
        alast = "acat"
        if p.settings.music and p.settings.music_file and (pdir / p.settings.music_file).exists():
            inputs += ["-stream_loop", "-1", "-i", str(pdir / p.settings.music_file)]
            graph.append(f"[{2 * n}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                         f"atrim=duration={offset:.3f},volume='{_duck_expr(spans)}':eval=frame[mus]")
            graph.append("[acat][mus]amix=inputs=2:duration=first:normalize=0[aout]")
            alast = "aout"
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs,
               "-filter_complex", ";".join(graph), "-map", f"[{vlast}]", "-map", f"[{alast}]",
               "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p", "-r", str(fps),
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", str(tmp_out)]
        proc = procs.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            m = _TIME.match(line.strip())
            if on_progress and m and total_ms:
                on_progress(min(1.0, int(m.group(1)) / 1000 / total_ms))
        err = proc.stderr.read()
        rc = proc.wait(); procs.done(proc)
        if rc != 0 or not tmp_out.exists():
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg lỗi khi ghép video:\n" + err[-1200:])
    os.replace(tmp_out, out)
    return out
