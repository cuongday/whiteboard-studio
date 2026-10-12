import json
import subprocess
import pytest
import numpy as np
import soundfile as sf
from studio import config, pipeline, store, versions
from studio.models import Element, Scene, Settings
from tests.test_annotate import make_scene

pytestmark = pytest.mark.skipif(not (config.COMPOSER_DIR / "node_modules").exists(), reason="composer not installed")


def seg(text, aspect, model=None):
    return [Scene(id=f"{i:02d}", text=t, visual_description="v", elements=[Element(label="a", say=t.split()[0]),
            Element(label="b", say=t.split()[-1].strip("."))], image_prompt="p") for i, t in enumerate(["Giá cả tăng nhanh.", "Tiền mất giá."], 1)]


def img(prompt, aspect, out, model=None):
    make_scene(out)
    return out


def synth(text, voice, out_wav):
    rate = 24000
    sf.write(out_wav, 0.05 * np.sin(np.linspace(0, 440 * 2 * np.pi * 2, rate * 2)), rate)
    words = [{"text": w, "start_ms": 300 + i * 300, "end_ms": 550 + i * 300} for i, w in enumerate(text.split())]
    out_wav.with_name("words.json").write_text(json.dumps(words, ensure_ascii=False))
    return words


def test_e2e_two_scenes():
    p = store.create_project("e2e", Settings(aspect="16:9", captions=True), "x")
    d = pipeline.Deps(segment=seg, gen_image=img, synth=synth)
    pipeline.run_segment(p.id, d)
    pipeline.run_images(p.id, d)
    pipeline.run_render(p.id, d)
    out = versions.vdir(p.id, "v1") / "final.mp4"
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(out)]))
    kinds = {s["codec_type"] for s in probe["streams"]}
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert kinds == {"video", "audio"}
    assert (v["width"], v["height"]) == (1920, 1080)
    assert abs(float(probe["format"]["duration"]) - 4.0) < 0.3


def test_e2e_edit_scene_and_new_version():
    p = store.create_project("e2e2", Settings(aspect="16:9", captions=True), "x")
    d = pipeline.Deps(segment=seg, gen_image=img, synth=synth)
    pipeline.run_segment(p.id, d); pipeline.run_images(p.id, d); pipeline.run_render(p.id, d)
    q = store.load(p.id); q.scenes[1].narration = "Tiền mất giá trị."; versions.invalidate_scene(q, "02", "voice"); store.save(q)
    pipeline.run_rebuild_scene(p.id, d, version="v1", scene="02")
    assert (versions.vscene_dir(p.id, "v1", "02") / "preview.mp4").exists()
    pipeline.run_compose(p.id, d, version="v1")
    v1_final = versions.vdir(p.id, "v1") / "final.mp4"; before = v1_final.stat().st_mtime
    pipeline.run_new_version(p.id, d, voice="Mai Anh")
    v2_final = versions.vdir(p.id, "v2") / "final.mp4"
    assert v1_final.stat().st_mtime == before and v2_final.exists()
    for f in (v1_final, v2_final):
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(f)]))
        assert abs(float(probe["format"]["duration"]) - 4.0) < 0.3
