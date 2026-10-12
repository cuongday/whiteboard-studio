import json
from studio import compose, store, config
from studio.models import Settings, Scene

def test_build_props(tmp_projects):
    p = store.create_project("t", Settings(aspect="9:16", captions=False, music=True, music_file="uploads/m.mp3"), "")
    p.scenes = [Scene(id="01", text="a", duration_ms=2000), Scene(id="02", text="b", duration_ms=1010)]
    for s in p.scenes:
        (store.scene_dir(p.id, s.id) / "words.json").write_text(json.dumps([{"text": "a", "start_ms": 0, "end_ms": 10}]))
    props = compose.build_props(p)
    assert (props["width"], props["height"], props["fps"]) == (1080, 1920, config.FPS)
    assert props["captions"] is False and props["music"] == "uploads/m.mp3"
    assert props["scenes"][0] == {"clip": "scenes/01/clip.mp4", "audio": "scenes/01/voice.wav",
                                  "durationInFrames": 60, "words": [{"text": "a", "start_ms": 0, "end_ms": 10}]}
    assert props["scenes"][1]["durationInFrames"] == 31

def test_render_retries_transient_then_succeeds(tmp_projects, monkeypatch):
    p = store.create_project("t", Settings(), "")
    calls = []
    def fake_run(cmd, on_progress):
        calls.append(cmd)
        if len(calls) == 1:
            return False, ["Rendered 10/20\n", "net::ERR_NETWORK_CHANGED\n"]
        (store.project_dir(p.id) / "final.mp4").write_bytes(b"x")
        return True, []
    monkeypatch.setattr(compose, "_run_remotion", fake_run)
    assert compose.render_final(p).name == "final.mp4"
    assert len(calls) == 2
    assert any(a.startswith("--offthreadvideo-cache-size-in-bytes=") for a in calls[0])

def test_render_non_transient_fails_fast_with_clean_message(tmp_projects, monkeypatch):
    import pytest
    p = store.create_project("t", Settings(), "")
    calls = []
    def fake_run(cmd, on_progress):
        calls.append(1)
        return False, ["Rendered 1/20\n"] * 30 + ["TypeError: boom\n"]
    monkeypatch.setattr(compose, "_run_remotion", fake_run)
    with pytest.raises(RuntimeError) as e:
        compose.render_final(p)
    assert len(calls) == 1
    assert "TypeError: boom" in str(e.value) and "Rendered 1/20" not in str(e.value)
