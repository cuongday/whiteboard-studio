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
