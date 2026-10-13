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

LEAD_MS = 300        # first stroke right after the scene starts
TAIL_MS = 500        # finished picture stays on screen before the next scene
MIN_DRAW_MS = 800

def _area(e: dict) -> float:
    r = e.get("bbox") or e.get("region") or {}
    return max(1.0, float(r.get("width", 1)) * float(r.get("height", 1)))

def schedule(anchors: list[int | None], weights: list[float], duration_ms: int) -> list[tuple[int, int]]:
    """(startMs, durationMs) per element. The pen never idles: element 0 starts at LEAD_MS, each element
    draws until the next one starts, the last one ends TAIL_MS before the scene ends. Phrase anchors only
    pull a start half-way towards the moment it is spoken; every element keeps a minimum share that grows with
    its size, so close anchors cannot squeeze a big drawing into a scribble."""
    n = len(anchors)
    end = max(LEAD_MS + MIN_DRAW_MS * n, duration_ms - TAIL_MS)
    span = end - LEAD_MS
    total_w = sum(weights) or 1.0
    # half the time is reserved by size, the other half follows the narration
    mins = [max(min(MIN_DRAW_MS, span / n), 0.5 * span * w / total_w) for w in weights]
    starts = [float(LEAD_MS)]
    for i in range(1, n):
        even = LEAD_MS + span * sum(weights[:i]) / total_w
        # halfway between "when it is spoken" and "fair share by size": follows the narration
        # without letting clustered phrases leave one element a huge slow stretch
        want = even if anchors[i] is None else (anchors[i] + even) / 2
        lo = starts[-1] + mins[i - 1]
        hi = end - sum(mins[i:])
        starts.append(min(max(want, lo), hi))
    bounds = [int(round(x)) for x in starts] + [int(end)]
    return [(bounds[i], bounds[i + 1] - bounds[i]) for i in range(n)]

def build_annotation(image: Path, elements: list[Element], words: list[dict], duration_ms: int) -> dict:
    k = max(1, len(elements)) if elements else None
    ann = auto_annotate.annotate(image, k=k, labels=[e.label for e in elements] or None,
                                 says=[e.say for e in elements] or None, duration_ms=duration_ms)
    els = ann["elements"]
    anchors = [find_phrase_ms(words, e["say"]) if e.get("say") else None for e in els]
    for e, (start, dur) in zip(els, schedule(anchors, [_area(e) for e in els], int(duration_ms))):
        e["reveal"]["startMs"] = start
        e["reveal"]["durationMs"] = dur
        e["subtitle"] = e.get("say", "")
    ann["sceneDurationMs"] = int(duration_ms)
    return ann
