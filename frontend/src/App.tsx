import { useCallback, useEffect, useRef, useState } from "react";
import { api, JobEvent, Project } from "./api";
import { stageLabel } from "./labels";
import NewProject from "./steps/NewProject";
import ScenesReview from "./steps/ScenesReview";
import ImagesReview from "./steps/ImagesReview";
import RenderView from "./steps/RenderView";

export type EditMode = null | "scenes" | "images";

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [list, setList] = useState<Project[]>([]);
  const [ev, setEv] = useState<JobEvent | null>(null);
  const [checks, setChecks] = useState<{ name: string; ok: boolean; hint: string }[]>([]);
  const [edit, setEdit] = useState<EditMode>(null);
  const [session, setSession] = useState(0);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [renderCount, setRenderCount] = useState(0);
  const [err, setErr] = useState("");
  const seq = useRef(0);
  const idRef = useRef<string | null>(null);
  const wasBusy = useRef(false);
  const inputPending = useRef(false);
  idRef.current = project?.id ?? idRef.current;
  inputPending.current = !!project && project.stage === "input" && !project.job_error;

  useEffect(() => { api.list().then(setList).catch(() => {}); api.health().then((h) => setChecks(h.checks)).catch(() => {}); }, []);

  const reload = useCallback(async () => {
    const id = idRef.current; if (!id) return;
    const n = ++seq.current;
    try {
      const p = await api.get(id);
      if (n === seq.current && idRef.current === id) setProject(p);
    } catch { /* transient */ }
  }, []);

  const open = useCallback((p: Project | null) => {
    seq.current++; idRef.current = p?.id ?? null; wasBusy.current = false;
    setEv(null); setEdit(null); setBusy(false); setErr(""); setProject(p);
    if (!p) api.list().then(setList).catch(() => {});
  }, []);
  const openById = async (id: string) => {
    try { open(await api.get(id)); } catch (e) { setErr(String((e as Error).message)); }
  };
  const beginAction = useCallback(() => { setEv(null); setErr(""); }, []);
  const afterAction = useCallback(() => { setBusy(true); wasBusy.current = true; reload(); }, [reload]);
  const setFromChild = useCallback((p: Project) => { seq.current++; setProject(p); setEdit(null); }, []);
  const startEdit = useCallback((m: EditMode) => { if (m === "scenes") setSession((s) => s + 1); setEdit(m); }, []);

  const pid = project?.id;
  useEffect(() => {
    if (!pid) return;
    return api.events(pid, (e) => { setEv(e); if (e.type !== "progress") reload(); }, reload);
  }, [pid, reload]);

  // poll while this project's job runs (or segmentation is pending)
  useEffect(() => {
    if (!pid) return;
    let alive = true;
    const t = async () => {
      let b = false;
      try { const j = await api.jobs(); b = j.busy && j.pid === pid; } catch { return; }
      if (!alive) return;
      setBusy(b);
      if (b || wasBusy.current || inputPending.current) await reload();
      if (wasBusy.current && !b) setTick((x) => x + 1);
      wasBusy.current = b;
    };
    t();
    const h = setInterval(t, 2000);
    return () => { alive = false; clearInterval(h); };
  }, [pid, reload]);

  const stage = project?.stage;
  useEffect(() => { if (stage === "done") setRenderCount((c) => c + 1); }, [stage, pid]);

  const retry = async () => {
    if (!project) return; beginAction();
    try { await api.segment(project.id); afterAction(); } catch (e) { setErr(String((e as Error).message)); }
  };

  const bad = checks.filter((c) => !c.ok);
  const showScenes = project && (stage === "scenes" || edit === "scenes");
  const showImages = project && !showScenes && (stage === "images" || edit === "images");
  const showRender = project && !showScenes && !showImages && (stage === "rendering" || stage === "done");
  return (
    <div className="app">
      <header>
        <h1 onClick={() => open(null)}>Whiteboard Studio</h1>
        {project && <span className="muted">{project.title} · {project.settings.aspect} · {stageLabel(project.stage)}</span>}
      </header>
      {bad.length > 0 && <div className="warn">{bad.map((c) => <div key={c.name}>⚠ {c.name}: {c.hint}</div>)}</div>}
      {ev && ev.type === "progress" && <div className="progress"><div style={{ width: `${ev.pct * 100}%` }} /><span>{ev.msg}</span></div>}
      {ev && ev.type === "error" && <div className="error">Lỗi: {ev.msg}</div>}
      {err && <div className="error">{err}</div>}
      {!project && <NewProject list={list} onCreated={open} onOpen={openById} />}
      {project?.stage === "input" && (project.job_error
        ? <div className="card">
            <div className="error">Chia cảnh thất bại: {project.job_error}</div>
            <div className="row"><button disabled={busy} onClick={retry}>Thử lại</button><button onClick={() => open(null)}>← Về danh sách</button></div>
          </div>
        : <p className="muted">Gemini đang chia cảnh…</p>)}
      {showScenes && <ScenesReview key={`${project.id}:${session}`} project={project} busy={busy}
        onChange={setFromChild} beginAction={beginAction} afterAction={afterAction} />}
      {showImages && <ImagesReview project={project} busy={busy} tick={tick} beginAction={beginAction} afterAction={afterAction}
        onEditScenes={() => startEdit("scenes")} onRender={() => setEdit(null)} />}
      {showRender && <RenderView project={project} busy={busy} version={renderCount} onRefresh={reload}
        onEdit={startEdit} />}
    </div>
  );
}
