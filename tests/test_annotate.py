import cv2
import numpy as np
from studio.annotate import build_annotation, find_phrase_ms
from studio.models import Element

WORDS = [{"text": t, "start_ms": 300 + i * 400, "end_ms": 300 + i * 400 + 350}
         for i, t in enumerate("Giá cả tăng nhanh, tiền mất giá.".split())]

def make_scene(path):
    img = np.full((540, 960, 3), (215, 235, 245), np.uint8)   # BGR of #F5EBD7
    cv2.circle(img, (200, 270), 80, (60, 60, 60), 6)
    cv2.rectangle(img, (650, 170), (850, 370), (60, 60, 60), 6)
    cv2.imwrite(str(path), img)
    return path

def test_find_phrase_ms():
    assert find_phrase_ms(WORDS, "tiền mất") == 300 + 4 * 400
    assert find_phrase_ms(WORDS, "TĂNG") == 300 + 2 * 400
    assert find_phrase_ms(WORDS, "không có") is None

def test_build_annotation_uses_phrase_times(tmp_path):
    img = make_scene(tmp_path / "image.png")
    els = [Element(label="coin", say="tăng"), Element(label="box", say="tiền mất")]
    ann = build_annotation(img, els, WORDS, 6000)
    assert ann["sceneDurationMs"] == 6000
    assert len(ann["elements"]) == 2
    starts = [e["reveal"]["startMs"] for e in ann["elements"]]
    assert starts == [1100, 1900]
    assert ann["elements"][0]["label"] == "coin"
    last = ann["elements"][-1]["reveal"]
    assert last["startMs"] + last["durationMs"] <= 6000 - 300
