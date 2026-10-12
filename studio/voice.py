import json
import os
import re
import threading
from pathlib import Path
from typing import TypedDict
import numpy as np
import soundfile as sf

LEAD_MS, GAP_MS, TAIL_MS = 300, 250, 600
_LOCK = threading.Lock()
_TTS = {}

class Word(TypedDict):
    text: str
    start_ms: int
    end_ms: int

def get_tts():
    if "t" not in _TTS:
        try:
            from vieneu import Vieneu
        except ImportError as e:
            raise RuntimeError("Chưa cài VieNeu: pip install vieneu") from e
        _TTS["t"] = Vieneu(mode=os.environ.get("VIENEU_MODE", "v3turbo"))
    return _TTS["t"]

DEFAULT_VOICE = "Hải Đăng"
_VOICES: list[dict] = []

def list_voices(tts=None) -> list[dict]:
    """Preset VieNeu voices as [{id, label}]; falls back to the default voice if VieNeu can't load."""
    if _VOICES:
        return _VOICES
    try:
        presets = (tts or get_tts()).list_preset_voices()
    except Exception:  # noqa: BLE001
        return [{"id": DEFAULT_VOICE, "label": DEFAULT_VOICE}]
    _VOICES.extend({"id": vid, "label": label.lstrip("⭐ ").strip()} for label, vid in presets)
    return _VOICES

def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]

def _silence(ms: int, rate: int) -> np.ndarray:
    return np.zeros(int(rate * ms / 1000), dtype=np.float32)

def synthesize(text: str, voice_name: str, out_wav: Path, tts=None) -> list[Word]:
    tts = tts or get_tts()
    rate = tts.sample_rate
    chunks = [_silence(LEAD_MS, rate)]
    t = LEAD_MS
    words: list[Word] = []
    sentences = split_sentences(text)
    for i, sent in enumerate(sentences):
        with _LOCK:
            if tts.resolve_voice_name(voice_name) is None:
                raise RuntimeError(f"Không có giọng VieNeu {voice_name!r}")
            pcm = np.asarray(tts.infer(sent, voice=tts.get_preset_voice(voice_name)), dtype=np.float32).reshape(-1)
        dur = len(pcm) * 1000 / rate
        toks = sent.split()
        total_chars = sum(len(w) for w in toks) or 1
        acc = 0.0
        for w in toks:
            s = t + dur * acc / total_chars
            acc += len(w)
            words.append({"text": w, "start_ms": round(s), "end_ms": round(t + dur * acc / total_chars)})
        chunks.append(pcm)
        t += dur
        if i < len(sentences) - 1:
            chunks.append(_silence(GAP_MS, rate)); t += GAP_MS
    chunks.append(_silence(TAIL_MS, rate))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, np.concatenate(chunks), rate, subtype="PCM_16")
    out_wav.with_name("words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words

def wav_duration_ms(path: Path) -> int:
    info = sf.info(path)
    return round(info.frames * 1000 / info.samplerate)
