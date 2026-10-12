import re
import sys
import unicodedata
from pathlib import Path
from .models import Element

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
import auto_annotate  # noqa: E402

def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", s).lower())

def find_phrase_ms(words: list[dict], phrase: str) -> int | None:
    target = [_norm(t) for t in phrase.split() if _norm(t)]
    toks = [_norm(w["text"]) for w in words]
    if not target:
        return None
    for i in range(len(toks) - len(target) + 1):
        if toks[i:i + len(target)] == target:
            return words[i]["start_ms"]
    return None

def build_annotation(image: Path, elements: list[Element], words: list[dict], duration_ms: int) -> dict:
    k = max(1, len(elements)) if elements else None
    ann = auto_annotate.annotate(image, k=k, labels=[e.label for e in elements] or None,
                                 says=[e.say for e in elements] or None, duration_ms=duration_ms)
    els = ann["elements"]
    n = len(els)
    end_limit = duration_ms - 300
    slot = (end_limit - 300) / max(1, n)
    starts = []
    for i, e in enumerate(els):
        ms = find_phrase_ms(words, e.get("say", "")) if e.get("say") else None
        fallback = int(300 + i * slot)
        ms = fallback if ms is None else ms
        if starts and ms <= starts[-1]:
            ms = starts[-1] + 400
        starts.append(min(ms, end_limit - 800))
    for i, e in enumerate(els):
        nxt = starts[i + 1] if i + 1 < n else end_limit
        e["reveal"]["startMs"] = starts[i]
        e["reveal"]["durationMs"] = max(800, min(int(slot * 1.2), nxt - starts[i]))
        e["subtitle"] = e.get("say", "")
    ann["sceneDurationMs"] = int(duration_ms)
    return ann
