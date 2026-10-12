import { useState } from "react";
import { api, Project } from "../api";

export default function ImagesReview({ project, onChange, reload }: { project: Project; onChange: (p: Project) => void; reload: () => void }) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const run = async (f: () => Promise<unknown>) => { setErr(""); try { await f(); reload(); } catch (e) { setErr(String((e as Error).message)); } };
  const allDone = project.scenes.every((s) => s.status.image === "done");
  return (
    <div>
      <h2>Bước 2 · Duyệt ảnh</h2>
      {err && <div className="error">{err}</div>}
      {project.job_error && <div className="error">{project.job_error}</div>}
      <div className={`thumbs ${project.settings.aspect === "9:16" ? "portrait" : ""}`}>
        {project.scenes.map((s) => (
          <div className="card" key={s.id}>
            <b>Cảnh {s.id}</b> <span className={`badge ${s.status.image}`}>{s.status.image}</span>
            {s.status.image === "done"
              ? <img src={api.file(project.id, `scenes/${s.id}/image.png`, project.created_at + s.image_prompt.length + s.status.image)} />
              : <div className="placeholder">{s.status.image === "running" ? "Đang vẽ…" : s.error ?? "Chưa có ảnh"}</div>}
            <p className="small">{s.text}</p>
            <details><summary>Sửa prompt</summary>
              <textarea rows={5} value={prompts[s.id] ?? s.image_prompt} onChange={(e) => setPrompts({ ...prompts, [s.id]: e.target.value })} />
            </details>
            <button onClick={() => run(() => api.regenerate(project.id, s.id, prompts[s.id]))}>Tạo lại ảnh</button>
          </div>
        ))}
      </div>
      <div className="row sticky">
        <button onClick={() => onChange({ ...project, stage: "scenes" })}>← Sửa cảnh</button>
        <button onClick={() => run(() => api.approveScenes(project.id))}>Tạo các ảnh còn thiếu/lỗi</button>
        <button className="primary" disabled={!allDone} onClick={() => run(() => api.render(project.id))}>Duyệt → Lồng tiếng & render</button>
      </div>
    </div>
  );
}
