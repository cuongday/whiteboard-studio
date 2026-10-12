import json
import numpy as np
import soundfile as sf
from studio import voice

class FakeTTS:
    sample_rate = 24000
    def resolve_voice_name(self, v): return v
    def get_preset_voice(self, v): return v
    def infer(self, text, voice=None):
        return np.zeros(int(self.sample_rate * 0.1 * len(text.split())), dtype=np.float32)  # 100ms/word

def test_split_sentences():
    assert voice.split_sentences("Một hai. Ba bốn? Năm!\nSáu") == ["Một hai.", "Ba bốn?", "Năm!", "Sáu"]

def test_synthesize_timings(tmp_path):
    words = voice.synthesize("Một hai. Ba bốn năm.", "Hải Đăng", tmp_path / "voice.wav", tts=FakeTTS())
    assert [w["text"] for w in words] == ["Một", "hai.", "Ba", "bốn", "năm."]
    assert words[0]["start_ms"] == voice.LEAD_MS
    assert words[1]["end_ms"] == voice.LEAD_MS + 200
    assert words[2]["start_ms"] == voice.LEAD_MS + 200 + voice.GAP_MS
    data, sr = sf.read(tmp_path / "voice.wav")
    expect = voice.LEAD_MS + 200 + voice.GAP_MS + 300 + voice.TAIL_MS
    assert abs(len(data) / sr * 1000 - expect) < 2
    assert json.loads((tmp_path / "words.json").read_text())[4]["text"] == "năm."

def test_list_voices(monkeypatch):
    monkeypatch.setattr(voice, "_VOICES", [])
    class T:
        def list_preset_voices(self):
            return [("⭐ Hải Đăng — Nam · Bắc", "Hải Đăng"), ("Mai Anh — Nữ · Bắc", "Mai Anh")]
    assert voice.list_voices(T()) == [{"id": "Hải Đăng", "label": "Hải Đăng — Nam · Bắc"},
                                      {"id": "Mai Anh", "label": "Mai Anh — Nữ · Bắc"}]

def test_list_voices_fallback(monkeypatch):
    monkeypatch.setattr(voice, "_VOICES", [])
    class Broken:
        def list_preset_voices(self): raise RuntimeError("no model")
    assert voice.list_voices(Broken()) == [{"id": "Hải Đăng", "label": "Hải Đăng"}]

def test_pool_reuses_instances_and_caps(monkeypatch):
    import threading, time as _t
    made = []
    class Slow(FakeTTS):
        def infer(self, text, voice=None):
            _t.sleep(0.05); return super().infer(text, voice)
    monkeypatch.setattr(voice, "VOICE_WORKERS", 2)
    monkeypatch.setattr(voice, "_POOL", [])
    monkeypatch.setattr(voice, "_CREATED", [0])
    monkeypatch.setattr(voice, "_new_tts", lambda threads=0: made.append(threads) or Slow())
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    ts = [threading.Thread(target=voice.synthesize, args=("Một hai.", "Hải Đăng", tmp / f"{i}" / "voice.wav")) for i in range(6)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(made) == 2 and len(voice._POOL) == 2


def test_spans_written(tmp_path):
    voice.synthesize("Một hai. Ba bốn năm.", "Hải Đăng", tmp_path / "voice.wav", tts=FakeTTS())
    spans = json.loads((tmp_path / "spans.json").read_text())
    assert spans == [[voice.LEAD_MS, voice.LEAD_MS + 200],
                     [voice.LEAD_MS + 200 + voice.GAP_MS, voice.LEAD_MS + 200 + voice.GAP_MS + 300]]

def test_subtitle_same_as_narration_returns_narration_words():
    w = [{"text": "a", "start_ms": 0, "end_ms": 5}]
    assert voice.subtitle_words("a", "a", w, [[0, 5]]) is w

def test_subtitle_aligned_per_sentence():
    spans = [[300, 1300], [1550, 2550]]
    out = voice.subtitle_words("API mới. Rất nhanh.", "ây pi ai mới. Rất nhanh.", [], spans)
    assert [x["text"] for x in out] == ["API", "mới.", "Rất", "nhanh."]
    assert out[0]["start_ms"] == 300 and out[1]["end_ms"] == 1300
    assert out[2]["start_ms"] == 1550 and out[3]["end_ms"] == 2550

def test_subtitle_sentence_mismatch_spreads_over_speech():
    spans = [[300, 1000], [1250, 2000]]
    out = voice.subtitle_words("Một câu duy nhất", "Câu một. Câu hai.", [], spans)
    assert out[0]["start_ms"] == 300 and out[-1]["end_ms"] == 2000

def test_subtitle_without_spans_uses_word_range():
    words = [{"text": "x", "start_ms": 100, "end_ms": 200}, {"text": "y", "start_ms": 200, "end_ms": 900}]
    out = voice.subtitle_words("A B", "x y", words, None)
    assert out[0]["start_ms"] == 100 and out[-1]["end_ms"] == 900

def test_borrow_timeout(monkeypatch):
    import pytest
    monkeypatch.setattr(voice, "VOICE_WORKERS", 1)
    monkeypatch.setattr(voice, "_POOL", [])
    monkeypatch.setattr(voice, "_CREATED", [1])     # the only instance is lent out
    with pytest.raises(TimeoutError):
        voice.synthesize("a", "Hải Đăng", __import__("pathlib").Path("/tmp/x.wav"), timeout=0.1)
