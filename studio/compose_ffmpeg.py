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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

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
SEG_WORKERS = int(os.environ.get("STUDIO_SEGMENT_WORKERS", str(max(1, min(4, (os.cpu_count() or 2) // 2)))))

def _run(cmd, total_s: float | None = None, on_progress=None) -> None:
    proc = procs.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            m = _TIME.match(line.strip())
            if on_progress and m and total_s:
                on_progress(min(1.0, int(m.group(1)) / 1e6 / total_s))
        err = proc.stderr.read()
        rc = proc.wait()
    finally:
        procs.done(proc)
    if rc != 0:
        raise RuntimeError("ffmpeg lỗi khi ghép video:\n" + err[-1200:])

def _segment(d: Path, frames: int, fps: int, w: int, h: int, words: list[dict], captions: bool) -> Path:
    """Scene clip -> captioned, exact-length H.264 segment; cached until clip/words/format change."""
    seg = d / "segment.mp4"
    key = json.dumps({"clip": (d / "clip.mp4").stat().st_mtime_ns, "frames": frames, "fps": fps, "size": [w, h],
                      "captions": captions, "words": words if captions else None, "preset": PRESET, "crf": CRF},
                     ensure_ascii=False, sort_keys=True)
    kf = d / "segment.key"
    if seg.exists() and kf.exists() and kf.read_text(encoding="utf-8") == key:
        return seg
    dur = frames / fps
    vf = (f"fps={fps},scale={w}:{h},setsar=1,format=yuv420p,"
          f"tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},setpts=PTS-STARTPTS")
    tmp = d / "segment.tmp.mp4"
    with tempfile.TemporaryDirectory(prefix="wbs-ass-") as td:
        if captions and words:
            ass = Path(td) / "c.ass"
            ass.write_text(build_ass([(0.0, words)], w, h), encoding="utf-8")
            vf += f",ass=filename={ass}:fontsdir={FONT_DIR}"
        _run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(d / "clip.mp4"), "-vf", vf,
              "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
              "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2), str(tmp)])
    os.replace(tmp, seg)
    kf.write_text(key, encoding="utf-8")
    return seg

def _narration(parts: list[tuple[Path, float]], out: Path) -> None:
    """All scene voices back to back, each padded/trimmed to its scene length."""
    chunks = []
    for wav, dur in parts:
        a, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        a = a.mean(axis=1)
        if sr != SAMPLE_RATE:
            idx = np.arange(int(len(a) * SAMPLE_RATE / sr)) * sr / SAMPLE_RATE
            a = np.interp(idx, np.arange(len(a)), a).astype("float32")
        n = round(dur * SAMPLE_RATE)
        chunks.append(np.pad(a[:n], (0, max(0, n - len(a)))))
    sf.write(str(out), np.concatenate(chunks) if chunks else np.zeros(1, "float32"), SAMPLE_RATE)

def render_final(p: Project, vid: str, on_progress=None) -> Path:
    """Incremental: unchanged scenes reuse their encoded segment; the final step only copies video."""
    v = versions.get(p, vid)
    pdir = store.project_dir(p.id)
    vd = versions.vdir(p.id, vid); vd.mkdir(parents=True, exist_ok=True)
    w, h = config.ASPECTS[p.settings.aspect]
    fps = config.FPS
    out = vd / "final.mp4"
    tmp_out = vd / "final.ffmpeg.tmp.mp4"
    report = on_progress or (lambda f: None)

    jobs, spans = [], []
    offset = 0.0
    for s in p.scenes:
        d = versions.vscene_dir(p.id, vid, s.id)
        frames = math.ceil((v.scenes[s.id].duration_ms or 0) * fps / 1000)
        words = json.loads((d / "words.json").read_text(encoding="utf-8")) if (d / "words.json").exists() else []
        if words:
            spans.append((offset * 1000 + words[0]["start_ms"], offset * 1000 + words[-1]["end_ms"]))
        jobs.append((d, frames, words))
        offset += frames / fps

    done = [0]
    def seg(job):
        d, frames, words = job
        r = _segment(d, frames, fps, w, h, words, p.settings.captions)
        done[0] += 1; report(0.9 * done[0] / max(1, len(jobs)))
        return r

    with tempfile.TemporaryDirectory(prefix="wbs-cat-") as td:
        audio = Path(td) / "audio.m4a"
        def encode_audio():
            # narration (+ ducked music) is encoded once, alongside the video segments
            narr = Path(td) / "narration.wav"
            _narration([(d / "voice.wav", f / fps) for d, f, _ in jobs], narr)
            cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(narr)]
            if p.settings.music and p.settings.music_file and (pdir / p.settings.music_file).exists():
                cmd += ["-stream_loop", "-1", "-i", str(pdir / p.settings.music_file), "-filter_complex",
                        f"[0:a]aformat=channel_layouts=stereo[voi];"
                        f"[1:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,atrim=duration={offset:.3f},"
                        f"volume='{_duck_expr(spans)}':eval=frame[mus];"
                        "[voi][mus]amix=inputs=2:duration=first:normalize=0[aout]", "-map", "[aout]"]
            else:
                cmd += ["-ac", "2"]
            _run(cmd + ["-c:a", "aac", "-aac_coder", "fast", "-b:a", "192k", str(audio)])
        with ThreadPoolExecutor(max_workers=max(1, SEG_WORKERS) + 1) as ex:
            fa = ex.submit(encode_audio)
            segs = list(ex.map(seg, jobs))
            fa.result()
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{str(x).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                               for x in segs), encoding="utf-8")
        try:
            _run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", f"{offset:.3f}",
                  "-movflags", "+faststart", str(tmp_out)])
        except Exception:
            tmp_out.unlink(missing_ok=True)
            raise
    os.replace(tmp_out, out)
    report(1.0)
    return out
