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
