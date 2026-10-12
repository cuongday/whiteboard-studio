import json
import subprocess
from studio import compose, store, config, versions
from studio.models import Settings, Scene

def test_build_props(tmp_projects):
    p = store.create_project("t", Settings(aspect="9:16", captions=False, music=True, music_file="uploads/m.mp3"), "")
    p.scenes = [Scene(id="01", text="a"), Scene(id="02", text="b")]
    versions.ensure(p)
    for sid, ms in (("01", 2000), ("02", 1010)):
        versions.get(p).scenes[sid].duration_ms = ms
        (versions.vscene_dir(p.id, "v1", sid) / "words.json").write_text(json.dumps([{"text": "a", "start_ms": 0, "end_ms": 10}]))
    props = compose.build_props(p, "v1")
    assert (props["width"], props["height"], props["fps"]) == (1080, 1920, config.FPS)
    assert props["captions"] is False and props["music"] == "uploads/m.mp3"
    assert props["scenes"][0] == {"clip": "versions/v1/scenes/01/clip.mp4", "audio": "versions/v1/scenes/01/voice.wav",
                                  "durationInFrames": 60, "words": [{"text": "a", "start_ms": 0, "end_ms": 10}]}
    assert props["scenes"][1]["durationInFrames"] == 31

def test_make_preview(tmp_path):
    clip, wav, out = tmp_path / "c.mp4", tmp_path / "v.wav", tmp_path / "p.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=320x240:d=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=1.5", str(wav)], check=True)
    compose.make_preview(clip, wav, out)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)]))
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}

def test_render_retries_transient_then_succeeds(tmp_projects, monkeypatch):
    p = store.create_project("t", Settings(), "")
    p = store.load(p.id)
    calls = []
    def fake_run(cmd, on_progress):
        calls.append(cmd)
        if len(calls) == 1:
            return False, ["Rendered 10/20\n", "net::ERR_NETWORK_CHANGED\n"]
        (versions.vdir(p.id, "v1")).mkdir(parents=True, exist_ok=True)
        (versions.vdir(p.id, "v1") / "final.mp4").write_bytes(b"x")
        return True, []
    monkeypatch.setattr(compose, "_run_remotion", fake_run)
    assert compose.render_final(p, "v1").name == "final.mp4"
    assert len(calls) == 2
    assert any(a.startswith("--offthreadvideo-cache-size-in-bytes=") for a in calls[0])

def test_render_non_transient_fails_fast_with_clean_message(tmp_projects, monkeypatch):
    import pytest
    p = store.create_project("t", Settings(), "")
    p = store.load(p.id)
    calls = []
    def fake_run(cmd, on_progress):
        calls.append(1)
        return False, ["Rendered 1/20\n"] * 30 + ["TypeError: boom\n"]
    monkeypatch.setattr(compose, "_run_remotion", fake_run)
    with pytest.raises(RuntimeError) as e:
        compose.render_final(p, "v1")
    assert len(calls) == 1
    assert "TypeError: boom" in str(e.value) and "Rendered 1/20" not in str(e.value)
