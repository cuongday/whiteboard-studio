import os
import uuid
from pathlib import Path
from . import config
from .models import Project, Settings

def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid

def scene_dir(pid: str, scene_id: str) -> Path:
    d = project_dir(pid) / "scenes" / scene_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def save(p: Project) -> None:
    from . import versions
    versions.sync_active(p)
    d = project_dir(p.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    tmp.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, d / "project.json")

def load(pid: str) -> Project:
    f = project_dir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    p = Project.model_validate_json(f.read_text(encoding="utf-8"))
    from . import versions
    if versions.ensure(p):
        save(p)
    return p

def create_project(title: str, settings: Settings, source_text: str) -> Project:
    p = Project(id=uuid.uuid4().hex[:10], title=title or "Dự án mới", settings=settings, source_text=source_text)
    save(p)
    return p

def list_projects() -> list[Project]:
    if not config.PROJECTS_DIR.exists():
        return []
    out = []
    for d in config.PROJECTS_DIR.iterdir():
        if not (d / "project.json").exists():
            continue
        try:
            out.append(load(d.name))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out, key=lambda p: p.created_at, reverse=True)
