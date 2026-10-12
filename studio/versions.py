"""Voice versions: scene content is shared, narration/clips/final video live per version.

Scene.status["voice"/"draw"], Scene.duration_ms and Project.final are a MIRROR of the active
version (written by sync_active on every store.save) so the progress bar and older code paths
keep working. VersionScene is the source of truth for those values.
"""
import os
import shutil
from pathlib import Path
from . import store
from .models import Project, Scene, Version, VersionScene

LEGACY_FILES = ("voice.wav", "words.json", "spans.json", "narration.json", "annotation.json", "clip.mp4", "preview.mp4")

def vdir(pid: str, vid: str) -> Path:
    return store.project_dir(pid) / "versions" / vid

def vscene_dir(pid: str, vid: str, sid: str) -> Path:
    d = vdir(pid, vid) / "scenes" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d

def get(p: Project, vid: str | None = None) -> Version:
    vid = vid or p.active_version
    for v in p.versions:
        if v.id == vid:
            return v
    raise KeyError(vid)

def label_for(n: int, voice: str) -> str:
    return f"Bản {n} · {voice}"

def narration_of(s: Scene) -> str:
    return s.narration.strip() or s.text

def effective_voice(v: Version, vs: VersionScene) -> str:
    return vs.voice or v.voice

def _migrate_legacy(p: Project) -> Version:
    """Move pre-version files into versions/v1. Idempotent at file level: never overwrites an
    existing destination (legacy file is left in place), so an interrupted run can be redone."""
    v = Version(id="v1", label=label_for(1, p.settings.voice), voice=p.settings.voice)
    pdir = store.project_dir(p.id)
    for s in p.scenes:
        v.scenes[s.id] = VersionScene(status={"voice": s.status.get("voice", "pending"),
                                              "draw": s.status.get("draw", "pending")},
                                      duration_ms=s.duration_ms)
        src = pdir / "scenes" / s.id
        for f in LEGACY_FILES:
            if (src / f).exists():
                dst = vscene_dir(p.id, "v1", s.id) / f
                if not dst.exists():
                    os.replace(src / f, dst)
    vfinal = vdir(p.id, "v1") / "final.mp4"
    if not vfinal.exists() and (pdir / "final.mp4").exists():
        vfinal.parent.mkdir(parents=True, exist_ok=True)
        os.replace(pdir / "final.mp4", vfinal)
    if vfinal.exists():
        v.final = "versions/v1/final.mp4"
        for vs in v.scenes.values():
            vs.composed = vs.status["draw"] == "done"
    return v

def ensure(p: Project) -> bool:
    """Create v1 (migrating pre-version files) and keep every version's scene keys == p.scenes.

    Returns True ONLY for structural changes (v1 created/migrated, active_version repaired,
    version scene keys added/removed). It also calls sync_active to refresh the in-memory
    mirror, but mirror-only differences do not count (save applies the mirror anyway).
    Matching is by scene id: callers that renumber scenes must call `renumber` first."""
    changed = False
    if not p.versions:
        p.versions = [_migrate_legacy(p)]
        p.active_version = "v1"
        changed = True
    if p.active_version not in {v.id for v in p.versions}:
        p.active_version = p.versions[0].id; changed = True
    ids = {s.id for s in p.scenes}
    for v in p.versions:
        for sid in ids - set(v.scenes):
            v.scenes[sid] = VersionScene(); changed = True
        for sid in set(v.scenes) - ids:
            del v.scenes[sid]; changed = True
    sync_active(p)
    return changed

def sync_active(p: Project) -> bool:
    try:
        v = get(p)
    except KeyError:
        return False
    changed = False
    for s in p.scenes:
        vs = v.scenes.get(s.id)
        if vs is None:
            continue
        mirrored = {"image": s.status.get("image", "pending"), "voice": vs.status.get("voice", "pending"), "draw": vs.status.get("draw", "pending")}
        if mirrored != s.status or s.duration_ms != vs.duration_ms:
            s.status = mirrored; s.duration_ms = vs.duration_ms; changed = True
    if p.final != v.final:
        p.final = v.final; changed = True
    return changed

def invalidate_scene(p: Project, sid: str, from_step: str, vid: str | None = None) -> None:
    """image: shared image + draw in all versions; voice: voice+draw; draw: draw only.
    vid limits the version part to one version (per-scene voice override)."""
    assert from_step in ("image", "voice", "draw"), from_step
    if from_step == "image":
        s = next((x for x in p.scenes if x.id == sid), None)
        if s is not None:
            s.status["image"] = "pending"; s.error = None
    for v in p.versions:
        if vid and v.id != vid:
            continue
        vs = v.scenes.setdefault(sid, VersionScene())
        if from_step == "voice":
            vs.status["voice"] = "pending"
        vs.status["draw"] = "pending"; vs.error = None; vs.composed = False

def _move_dirs(base: Path, old_ids: set[str], moves: dict[str, str]) -> None:
    if not base.exists():
        return
    referenced = set(moves.values())
    for oid in old_ids - referenced:
        shutil.rmtree(base / oid, ignore_errors=True)
    for oid in referenced:
        if (base / oid).exists():
            os.replace(base / oid, base / f"_tmp_{oid}")
    for nid, oid in moves.items():
        if (base / f"_tmp_{oid}").exists():
            os.replace(base / f"_tmp_{oid}", base / nid)

def renumber(p: Project, old_ids: set[str], moves: dict[str, str]) -> None:
    """Scenes were reordered/merged/deleted: moves maps new id -> old id of kept scenes."""
    _move_dirs(store.project_dir(p.id) / "scenes", old_ids, moves)
    for v in p.versions:
        _move_dirs(vdir(p.id, v.id) / "scenes", old_ids, moves)
        v.scenes = {nid: v.scenes[oid] for nid, oid in moves.items() if oid in v.scenes}

def add_version(p: Project, voice: str) -> Version:
    n = max((int(v.id[1:]) for v in p.versions), default=0) + 1
    v = Version(id=f"v{n}", label=label_for(n, voice), voice=voice,
                scenes={s.id: VersionScene() for s in p.scenes})
    p.versions.append(v)
    p.active_version = v.id
    return v
