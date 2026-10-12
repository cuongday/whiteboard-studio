import json
import subprocess
from studio.annotate import build_annotation
from studio.draw import render_clip
from studio.models import Element
from tests.test_annotate import make_scene, WORDS

def test_render_clip(tmp_path):
    img = make_scene(tmp_path / "image.png")
    ann = build_annotation(img, [Element(label="a", say="tăng"), Element(label="b", say="tiền")], WORDS, 3000)
    out = render_clip(img, ann, tmp_path / "clip.mp4", fps=15)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-print_format", "json",
                                                "-show_format", "-show_streams", str(out)]))
    assert abs(float(probe["format"]["duration"]) - 3.0) < 0.3
    assert probe["streams"][0]["width"] == 960
