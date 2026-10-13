import json
import subprocess
import numpy as np
import soundfile as sf
from studio import compose, compose_ffmpeg, store, versions
from studio.models import Scene, Settings

def _clip(path, secs, color="white", size="320x180"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={secs}:r=30",
                    "-pix_fmt", "yuv420p", str(path)], check=True)

def _probe(path):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json",
                                               "-show_format", "-show_streams", str(path)]))

def _project(captions=True, music=False):
    p = store.create_project("t", Settings(aspect="16:9", captions=captions, music=music), "x")
    p.scenes = [Scene(id="01", text="Một hai."), Scene(id="02", text="Ba bốn năm.")]
    versions.ensure(p)
    for sid, ms, clip_s in (("01", 1500, 1.0), ("02", 1000, 2.0)):      # clip shorter / longer than voice
        d = versions.vscene_dir(p.id, "v1", sid)
        _clip(d / "clip.mp4", clip_s)
        sf.write(d / "voice.wav", 0.1 * np.sin(np.linspace(0, 2 * np.pi * 440 * ms / 1000, 24 * ms)), 24000)
        (d / "words.json").write_text(json.dumps([{"text": "Một", "start_ms": 300, "end_ms": 600},
                                                  {"text": "hai.", "start_ms": 600, "end_ms": 900}]))
        versions.get(p).scenes[sid].duration_ms = ms
    store.save(p)
    return store.load(p.id)

def test_ffmpeg_compose_duration_streams_and_progress():
    p = _project()
    seen = []
    out = compose_ffmpeg.render_final(p, "v1", on_progress=seen.append)
    assert out == versions.vdir(p.id, "v1") / "final.mp4"
    pr = _probe(out)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    assert {s["codec_type"] for s in pr["streams"]} == {"video", "audio"}
    assert (v["width"], v["height"]) == (1920, 1080)
    assert abs(float(pr["format"]["duration"]) - 2.5) < 0.1          # 45 + 30 frames
    assert seen and seen[-1] > 0.9

def test_ffmpeg_compose_with_music(tmp_path):
    p = _project(music=True)
    mus = store.project_dir(p.id) / "uploads" / "music.wav"; mus.parent.mkdir()
    sf.write(mus, 0.2 * np.ones(24000), 24000)
    p.settings.music_file = "uploads/music.wav"; store.save(p)
    out = compose_ffmpeg.render_final(store.load(p.id), "v1")
    assert abs(float(_probe(out)["format"]["duration"]) - 2.5) < 0.1

def test_build_ass_karaoke_timing():
    ass = compose_ffmpeg.build_ass([(1000, [{"text": "Một", "start_ms": 300, "end_ms": 600},
                                             {"text": "hai.", "start_ms": 800, "end_ms": 1200}])], 1920, 1080)
    ev = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert ev[0] == "Dialogue: 0,0:00:01.20,0:00:02.50,Box,,0,0,0,,Một hai."
    assert ev[1].endswith("{\\k10}{\\k50}Một {\\k40}hai.")

def test_dispatch_by_setting(monkeypatch):
    p = _project()
    called = []
    monkeypatch.setattr(compose_ffmpeg, "render_final", lambda p, vid, on_progress=None: called.append("ffmpeg"))
    monkeypatch.setattr(compose, "render_remotion", lambda p, vid, on_progress=None: called.append("remotion"))
    compose.render_final(p, "v1")
    p.settings.composer = "remotion"; compose.render_final(p, "v1")
    assert called == ["ffmpeg", "remotion"]

def test_caption_lines_never_overlap():
    words = [{"text": t, "start_ms": 300 + 200 * i, "end_ms": 480 + 200 * i}
             for i, t in enumerate("Một hai ba. Bốn năm sáu bảy tám chín mười mười một.".split())]
    ass = compose_ffmpeg.build_ass([(0, words), (5000, words[:3])], 1080, 1920)
    def ms(t):
        h, m, s = t.split(":"); return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
    spans = [(ms(l.split(",")[1]), ms(l.split(",")[2])) for l in ass.splitlines() if l.startswith("Dialogue: 1,")]
    assert len(spans) == 4
    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
        assert a1 <= b0 and a0 < a1

def test_incremental_reuses_unchanged_segments():
    p = _project()
    compose_ffmpeg.render_final(p, "v1")
    seg1 = versions.vscene_dir(p.id, "v1", "01") / "segment.mp4"
    seg2 = versions.vscene_dir(p.id, "v1", "02") / "segment.mp4"
    m1, m2 = seg1.stat().st_mtime_ns, seg2.stat().st_mtime_ns
    _clip(versions.vscene_dir(p.id, "v1", "02") / "clip.mp4", 1.0, color="black")   # scene 02 redrawn
    out = compose_ffmpeg.render_final(store.load(p.id), "v1")
    assert seg1.stat().st_mtime_ns == m1 and seg2.stat().st_mtime_ns != m2
    assert abs(float(_probe(out)["format"]["duration"]) - 2.5) < 0.1
