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
    assert starts[0] == 300 and starts[1] >= 1900                         # first draws at once, second near its phrase
    assert ann["elements"][0]["label"] == "coin"
    last = ann["elements"][-1]["reveal"]
    assert last["startMs"] + last["durationMs"] == 6000 - 500

from studio.annotate import schedule

def _check_continuous(plan, duration):
    assert plan[0][0] == 300
    for (a, da), (b, _) in zip(plan, plan[1:]):
        assert a + da == b                                              # pen never idles
    assert plan[-1][0] + plan[-1][1] == duration - 500

def test_schedule_no_idle_gap_scene01():
    # scene 01: moon anchor 300, next phrases at 5143 / 6240 -> used to idle 3.3-5.1 s
    plan = schedule([300, 5143, 6240], [512 * 510, 84 * 121, 706 * 208], 8200)
    _check_continuous(plan, 8200)

def test_schedule_late_first_anchor_starts_at_once():
    plan = schedule([793, 6710], [1.0, 1.0], 9630)
    _check_continuous(plan, 9630)
    assert abs(plan[1][0] - 6710) < 1500 or plan[1][0] < 6710

def test_schedule_close_anchors_keep_min_share_by_size():
    plan = schedule([None, 2000, 2100, 2200], [4.0, 1.0, 1.0, 1.0], 10000)
    _check_continuous(plan, 10000)
    assert plan[0][1] >= 0.5 * 9200 * 4 / 7 - 1                         # big drawing gets its size share
    assert all(d >= 800 for _, d in plan)
