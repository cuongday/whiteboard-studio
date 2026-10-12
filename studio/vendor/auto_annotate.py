#!/usr/bin/env python3
"""
Automatic annotation for raster line-art: find the drawn objects and turn them
into annotation elements (regions + reading order + default timing).

The illustration style (clean line art, lots of empty paper) makes objects
separable: ink is dilated until strokes of one object merge, connected blobs
become candidate elements, tiny blobs are merged into their nearest
neighbour, and if ``--elements K`` is given the closest blobs are merged
until K remain.  Elements are ordered in reading order (rows, then left to
right) unless ``--order`` says otherwise.

An agent should still look at the result (``render_annotation_preview.py``)
and rename / reorder / set ``say`` phrases.

Usage:
  python auto_annotate.py scene.png [--elements 4] [--order reading|ltr|ttb|size]
                          [--labels "Mặt trời,Mây,Người"] [--say "mặt trời,đám mây,người"]
                          [--duration-ms 9000] [--out scene.annotation.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stream_render as sr  # noqa: E402


def content_mask(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(3, min(h, w) // 50)
    corners = [img[:m, :m], img[:m, -m:], img[-m:, :m], img[-m:, -m:]]
    bg = np.median(np.concatenate([c.reshape(-1, 3) for c in corners]), axis=0)
    diff = np.abs(img.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10) < 10
    mask = (diff > 45) | ink
    # drop paper texture / noise specks
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return mask > 0


def _gap(a, b) -> float:
    """Distance between two boxes (0 if they overlap)."""
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return float(np.hypot(dx, dy))


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def detect_boxes(img: np.ndarray, k: int | None = None, merge_ratio: float = 0.014,
                 min_area_ratio: float = 0.01) -> list[tuple[int, int, int, int]]:
    h, w = img.shape[:2]
    mask = content_mask(img)
    # long thin horizontal strokes (ground lines, baselines) glue unrelated objects
    # together: ignore them while grouping (they are still drawn - pixels stay in `mask`)
    m8 = mask.astype(np.uint8)
    thin = m8 - cv2.morphologyEx(m8, cv2.MORPH_OPEN, np.ones((max(3, h // 90), 1), np.uint8))
    lines = cv2.morphologyEx(thin, cv2.MORPH_OPEN, np.ones((1, max(15, w // 12)), np.uint8))
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
    group_mask = (m8 > 0) & ~(lines > 0)
    r = max(3, int(min(h, w) * merge_ratio))
    blobs = cv2.dilate(group_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(blobs)
    boxes, areas = [], []
    for i in range(1, n):
        x, y, bw, bh, _a = st[i]
        sub = group_mask[y:y + bh, x:x + bw] & (lab[y:y + bh, x:x + bw] == i)
        ys, xs = np.nonzero(sub)
        if ys.size == 0:
            continue
        boxes.append((x + int(xs.min()), y + int(ys.min()), x + int(xs.max()) + 1, y + int(ys.max()) + 1))
        areas.append(int(ys.size))
    if not boxes:
        return []
    # merge small blobs into their nearest neighbour
    min_area = min_area_ratio * group_mask.sum()
    changed = True
    while changed and len(boxes) > 1:
        changed = False
        i = int(np.argmin(areas))
        if areas[i] < min_area:
            j = min((j for j in range(len(boxes)) if j != i), key=lambda j: _gap(boxes[i], boxes[j]))
            boxes[j] = _union(boxes[i], boxes[j])
            areas[j] += areas[i]
            del boxes[i], areas[i]
            changed = True
    # merge boxes that sit (mostly) inside another one - motion lines, details
    def inside(a, b) -> float:
        iw = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        ih = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return iw * ih / max(1, (a[2] - a[0]) * (a[3] - a[1]))
    changed = True
    while changed and len(boxes) > 1:
        changed = False
        for i in range(len(boxes)):
            box_area = lambda b: (b[2] - b[0]) * (b[3] - b[1])  # noqa: E731
            j = next((j for j in range(len(boxes)) if j != i
                      and box_area(boxes[i]) < 0.25 * box_area(boxes[j])
                      and inside(boxes[i], boxes[j]) > 0.9), None)
            if j is not None:
                boxes[j] = _union(boxes[i], boxes[j])
                areas[j] += areas[i]
                del boxes[i], areas[i]
                changed = True
                break
    # merge down to k
    if k:
        while len(boxes) > k:
            best = None
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    u = _union(boxes[i], boxes[j])
                    cost = _gap(boxes[i], boxes[j]) + 0.15 * np.sqrt((u[2] - u[0]) * (u[3] - u[1]))
                    if best is None or cost < best[0]:
                        best = (cost, i, j)
            _, i, j = best
            boxes[i] = _union(boxes[i], boxes[j])
            areas[i] += areas[j]
            del boxes[j], areas[j]
    return boxes


def order_boxes(boxes, mode: str = "reading"):
    if mode == "ltr":
        return sorted(boxes, key=lambda b: (b[0] + b[2]) / 2)
    if mode == "ttb":
        return sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    if mode == "size":
        return sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    # reading order: group into rows by vertical overlap, rows top->bottom, items left->right
    rest = sorted(boxes, key=lambda b: b[1])
    rows: list[list] = []
    for b in rest:
        for row in rows:
            ry0 = min(x[1] for x in row)
            ry1 = max(x[3] for x in row)
            ov = min(ry1, b[3]) - max(ry0, b[1])
            if ov > 0.5 * min(ry1 - ry0, b[3] - b[1]):
                row.append(b)
                break
        else:
            rows.append([b])
    rows.sort(key=lambda row: min(x[1] for x in row))
    return [b for row in rows for b in sorted(row, key=lambda x: x[0])]


def annotate(image_path: str | Path, k: int | None = None, order: str = "reading",
             labels: list[str] | None = None, says: list[str] | None = None,
             duration_ms: int | None = None, pad_ratio: float = 0.012) -> dict:
    img = sr._imread_any(str(image_path))
    if img is None:
        raise FileNotFoundError(image_path)
    h, w = img.shape[:2]
    boxes = order_boxes(detect_boxes(img, k), order)
    pad = max(4, int(min(w, h) * pad_ratio))
    n = len(boxes)
    total = duration_ms or max(4000, 2600 * n + 1000)
    slot = (total - 900) / max(1, n)
    elements = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
        start = int(300 + i * slot)
        e = {
            "id": f"el_{i + 1}",
            "label": labels[i] if labels and i < len(labels) else f"Phần {i + 1}",
            "sequence": i + 1,
            "narrativeRole": "",
            "subtitle": "",
            "type": "object",
            "region": {"x": int(x0), "y": int(y0), "width": int(x1 - x0), "height": int(y1 - y0)},
            "reveal": {"direction": "left_to_right", "startMs": start,
                       "durationMs": int(max(800, slot - 200)), "maskPaddingPx": pad, "protectedRegions": []},
            "handPath": {"start": [int(x0), int((y0 + y1) / 2)], "end": [int(x1), int((y0 + y1) / 2)],
                         "easing": "easeInOut"},
        }
        if says and i < len(says) and says[i].strip():
            e["say"] = says[i].strip()
        elements.append(e)
    return {"sceneId": Path(image_path).stem, "canvas": {"width": w, "height": h},
            "storyBasis": "", "sceneDurationMs": int(total), "elements": elements}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Auto-annotate a raster scene")
    p.add_argument("image")
    p.add_argument("--elements", type=int, default=None, help="target number of elements")
    p.add_argument("--order", default="reading", choices=["reading", "ltr", "ttb", "size"])
    p.add_argument("--labels", default=None, help="comma separated labels, in drawing order")
    p.add_argument("--say", default=None, help="comma separated trigger phrases, in drawing order")
    p.add_argument("--duration-ms", type=int, default=None)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    split = lambda s: [x.strip() for x in s.split(",")] if s else None  # noqa: E731
    ann = annotate(a.image, a.elements, a.order, split(a.labels), split(a.say), a.duration_ms)
    out = Path(a.out) if a.out else Path(a.image).with_suffix("").with_suffix(".annotation.json")
    if not a.out:
        out = Path(a.image).parent / (Path(a.image).stem + ".annotation.json")
    out.write_text(json.dumps(ann, ensure_ascii=False, indent=2), encoding="utf-8")
    for e in ann["elements"]:
        print(f"  #{e['sequence']} {e['label']}: {e['region']}")
    print(f"OUTPUT={out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
