import { useEffect, useRef, useState } from "react";
import { api, Project } from "../api";
import { stepLabel } from "../labels";

type Props = { project: Project; busy: boolean; tick: number; beginAction: () => void; afterAction: () => void;
  onEditScenes: () => void; onRender: () => void };

export default function ImagesReview({ project, busy, tick, beginAction, afterAction, onEditScenes, onRender }: Props) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [regen, setRegen] = useState<Record<string, number>>({});
  const [doneAt, setDoneAt] = useState<Record<string, number>>({});
  const prev = useRef<Record<string, string>>(Object.fromEntries(project.scenes.map((s) => [s.id, s.status.image])));
  useEffect(() => {
    const changed: Record<string, number> = {};
    for (const s of project.scenes) {
      if (s.status.image === "done" && prev.current[s.id] !== "done") changed[s.id] = Date.now();
    }
    prev.current = Object.fromEntries(project.scenes.map((s) => [s.id, s.status.image]));
    if (Object.keys(changed).length) setDoneAt((d) => ({ ...d, ...changed }));
  }, [project]);
  const run = async (f: () => Promise<unknown>, after?: () => void) => {
    setErr(""); beginAction();
    try { await f(); after?.(); afterAction(); } catch (e) { setErr(String((e as Error).message)); }
  };
  const allDone = project.scenes.every((s) => s.status.image === "done");
  return (
    <div>
      <h2>Duyệt ảnh</h2>
      {err && <div className="error">{err}</div>}
      {project.job_error && <div className="error">{project.job_error}</div>}
      <div className={`thumbs ${project.settings.aspect === "9:16" ? "portrait" : ""}`}>
        {project.scenes.map((s) => (
          <div className="card" key={s.id}>
            <b>Cảnh {s.id}</b> <span className={`badge ${s.status.image}`}>{stepLabel(s.status.image)}</span>
            {s.status.image === "done"
              ? <img src={api.file(project.id, `scenes/${s.id}/image.png`, `${project.created_at}-${regen[s.id] ?? 0}-${doneAt[s.id] ?? 0}-${tick}`)} />
              : <div className="placeholder">{s.status.image === "running" ? "Đang vẽ…" : s.error ?? "Chưa có ảnh"}</div>}
            <p className="small">{s.text}</p>
            <details><summary>Sửa prompt</summary>
              <textarea rows={5} value={prompts[s.id] ?? s.image_prompt} onChange={(e) => setPrompts({ ...prompts, [s.id]: e.target.value })} />
            </details>
            <button disabled={busy} onClick={() => run(() => api.regenerate(project.id, s.id, prompts[s.id]),
              () => setRegen((r) => ({ ...r, [s.id]: (r[s.id] ?? 0) + 1 })))}>Tạo lại ảnh</button>
          </div>
        ))}
      </div>
      <div className="row sticky">
        <button disabled={busy} onClick={onEditScenes}>← Sửa cảnh</button>
        <button disabled={busy} onClick={() => run(() => api.approveScenes(project.id))}>Tạo các ảnh còn thiếu/lỗi</button>
        <button className="primary" disabled={!allDone || busy} onClick={() => run(() => api.render(project.id), onRender)}>Duyệt → Lồng tiếng & render</button>
      </div>
    </div>
  );
}
