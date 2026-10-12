import { useCallback, useEffect, useState } from "react";
import { api, JobEvent, Project } from "./api";
import NewProject from "./steps/NewProject";
import ScenesReview from "./steps/ScenesReview";
import ImagesReview from "./steps/ImagesReview";
import RenderView from "./steps/RenderView";

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [list, setList] = useState<Project[]>([]);
  const [ev, setEv] = useState<JobEvent | null>(null);
  const [checks, setChecks] = useState<{ name: string; ok: boolean; hint: string }[]>([]);

  useEffect(() => { api.list().then(setList); api.health().then((h) => setChecks(h.checks)); }, []);
  const reload = useCallback(async () => { if (project) setProject(await api.get(project.id)); }, [project?.id]);

  useEffect(() => {
    if (!project) return;
    return api.events(project.id, (e) => { setEv(e); if (e.type !== "progress") { reload(); } });
  }, [project?.id]);

  // also refresh periodically while a scene step is running so thumbnails/status update
  useEffect(() => {
    if (!ev || ev.type !== "progress") return;
    const t = setTimeout(reload, 1500); return () => clearTimeout(t);
  }, [ev]);

  const bad = checks.filter((c) => !c.ok);
  return (
    <div className="app">
      <header>
        <h1 onClick={() => { setProject(null); api.list().then(setList); }}>Whiteboard Studio</h1>
        {project && <span className="muted">{project.title} · {project.settings.aspect}</span>}
      </header>
      {bad.length > 0 && <div className="warn">{bad.map((c) => <div key={c.name}>⚠ {c.name}: {c.hint}</div>)}</div>}
      {ev && ev.type === "progress" && <div className="progress"><div style={{ width: `${ev.pct * 100}%` }} /><span>{ev.msg}</span></div>}
      {ev && ev.type === "error" && <div className="error">Lỗi: {ev.msg}</div>}
      {!project && <NewProject list={list} onOpen={setProject} />}
      {project?.stage === "input" && <p className="muted">Gemini đang chia cảnh…</p>}
      {project?.stage === "scenes" && <ScenesReview project={project} onChange={setProject} />}
      {project?.stage === "images" && <ImagesReview project={project} onChange={setProject} reload={reload} />}
      {(project?.stage === "rendering" || project?.stage === "done") && <RenderView project={project} onBack={reload} />}
    </div>
  );
}
