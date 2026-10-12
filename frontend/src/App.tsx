import { useCallback, useEffect, useRef, useState } from "react";
import { api, JobEvent, JobState, Project } from "./api";
import Timer from "./Timer";
import Stepper from "./Stepper";
import { pickProgress } from "./progress";
import { ModelSelect, useModels } from "./models";
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
  const [job, setJob] = useState<JobState | null>(null);
  const [tick, setTick] = useState(0);
  const [renderCount, setRenderCount] = useState(0);
  const [err, setErr] = useState("");
  const seq = useRef(0);
  const idRef = useRef<string | null>(null);
  const wasBusy = useRef(false);
  const inputPending = useRef(false);
  const remoteActive = useRef(false);
  idRef.current = project?.id ?? idRef.current;
  inputPending.current = !!project && project.stage === "input" && !project.job_error;
  // job may be running in another server process sharing projects/: keep refreshing from disk
  remoteActive.current = !!project && (project.stage === "rendering" || project.scenes.some((s) => Object.values(s.status).includes("running")));

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
      let js: JobState;
      try { js = await api.jobs(); b = js.busy && js.pid === pid; } catch { return; }
      if (!alive) return;
      setJob(b ? js : null);
      setBusy(b);
      if (b || wasBusy.current || inputPending.current || remoteActive.current) await reload();
      if (wasBusy.current && !b) setTick((x) => x + 1);
      wasBusy.current = b;
    };
    t();
    const h = setInterval(t, 2000);
    return () => { alive = false; clearInterval(h); };
  }, [pid, reload]);

  const stage = project?.stage;
  useEffect(() => { if (stage === "done") setRenderCount((c) => c + 1); }, [stage, pid]);

  const models = useModels();
  const [retryModel, setRetryModel] = useState("");
  const retry = async () => {
    if (!project) return; beginAction();
    try { await api.segment(project.id, retryModel || undefined); afterAction(); } catch (e) { setErr(String((e as Error).message)); }
  };

  const bad = checks.filter((c) => !c.ok);
  const running = busy || project?.stage === "rendering" || project?.scenes.some((s) => s.status.image === "running");
  const prog = project && running ? pickProgress(ev, job?.progress ?? null, project) : null;
  const showScenes = project && (stage === "scenes" || edit === "scenes");
  const showImages = project && !showScenes && (stage === "images" || edit === "images");
  const showRender = project && !showScenes && !showImages && (stage === "rendering" || stage === "done");
  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => open(null)} aria-label="Về danh sách dự án">
          <span className="brand-mark" aria-hidden="true" />
          <span>Whiteboard <em>Studio</em></span>
        </button>
        {project && <div className="crumb">
          <span className="crumb-title">{project.title}</span>
          <span className="pill">{project.settings.aspect}</span>
          <span className={`pill stage-${project.stage}`}>{stageLabel(project.stage)}</span>
        </div>}
      </header>
      {project && <div className="statusbar">
        <Stepper stage={project.stage} />
        <Timer startedAt={job?.started_at ?? null} kind={job?.kind ?? null} timings={project.timings} />
      </div>}
      {bad.length > 0 && <div className="warn">{bad.map((c) => <div key={c.name}>⚠ {c.name}: {c.hint}</div>)}</div>}
      {prog && <div className="progress" role="progressbar" aria-valuenow={Math.round(prog.pct * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div style={{ width: `${Math.min(100, prog.pct * 100)}%` }} /><span>{prog.msg}</span><b>{Math.round(prog.pct * 100)}%</b>
      </div>}
      {ev && ev.type === "error" && <div className="error">Lỗi: {ev.msg}</div>}
      {err && <div className="error">{err}</div>}
      {!project && <NewProject list={list} onCreated={open} onOpen={openById} />}
      {project?.stage === "input" && (project.job_error
        ? <div className="card">
            <div className="error">Chia cảnh thất bại: {project.job_error}</div>
            {models && <ModelSelect label="Model chia cảnh" options={models.text}
              value={retryModel || project.settings.text_model} onChange={setRetryModel} />}
            <div className="row"><button className="primary" disabled={busy} onClick={retry}>Thử lại</button><button onClick={() => open(null)}>← Về danh sách</button></div>
          </div>
        : <div className="card waiting"><span className="spinner" aria-hidden="true" />Gemini đang đọc kịch bản và chia cảnh…</div>)}
      {showScenes && <ScenesReview key={`${project.id}:${session}`} project={project} busy={busy}
        onChange={setFromChild} beginAction={beginAction} afterAction={afterAction} />}
      {showImages && <ImagesReview project={project} busy={busy} tick={tick} beginAction={beginAction} afterAction={afterAction}
        onEditScenes={() => startEdit("scenes")} onRender={() => setEdit(null)} />}
      {showRender && <RenderView project={project} busy={busy} version={renderCount} onRefresh={reload}
        onEdit={startEdit} />}
    </div>
  );
}
