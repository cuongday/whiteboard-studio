import cv2
import numpy as np
from studio import hand

def test_plain_marker_is_clean_hand(tmp_path, monkeypatch):
    monkeypatch.setattr(hand, "CACHE", tmp_path)
    assert hand.hand_png("") == hand.CLEAN_HAND
    assert hand.hand_png("   ") == hand.CLEAN_HAND

def test_branded_hand_cached_and_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(hand, "CACHE", tmp_path)
    a = hand.hand_png("Kênh Việt Nam", "#1F5BFF")
    assert a.parent == tmp_path and a.exists()
    assert hand.hand_png("Kênh   Việt Nam", "#1f5bff") == a          # normalised -> same cache file
    img = cv2.imread(str(a), cv2.IMREAD_UNCHANGED)
    clean = cv2.imread(str(hand.CLEAN_HAND), cv2.IMREAD_UNCHANGED)
    assert img.shape == clean.shape and img.shape[2] == 4
    changed = np.any(img[:, :, :3] != clean[:, :, :3], axis=2)
    assert changed.sum() > 500                                        # text drawn on the barrel
    assert np.array_equal(img[:, :, 3], clean[:, :, 3])               # silhouette unchanged
    assert hand.hand_png("Khác") != a

def test_normalize():
    assert hand.normalize(None, None) == ("", hand.DEFAULT_COLOR)
    assert hand.normalize("x" * 100, "red")[0] == "x" * hand.MAX_TEXT
    assert hand.normalize("a", "red")[1] == hand.DEFAULT_COLOR

def test_concurrent_first_use(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(hand, "CACHE", tmp_path)
    with ThreadPoolExecutor(6) as ex:
        outs = list(ex.map(lambda _: hand.hand_png("Đồng thời"), range(6)))
    assert len(set(outs)) == 1 and outs[0].exists()
