import { useEffect, useState } from "react";
import { api, Project, VersionScene } from "../api";
import CaptionedPreview from "../CaptionedPreview";
import SceneEditor from "./SceneEditor";

type Props = { project: Project; busy: boolean; version: number; beginAction: () => void; afterAction: () => void;
  onChange: (p: Project) => void; onEdit: (m: "scenes" | "images") => void };

const badge = (vs?: VersionScene) => {
  if (!vs) return ["pending", "Cần dựng lại"];
  if (vs.status.voice === "error" || vs.status.draw === "error") return ["error", "Lỗi"];
  if (vs.status.voice === "running" || vs.status.draw === "running") return ["running", "Đang chạy"];
  if (vs.status.voice !== "done" || vs.status.draw !== "done") return ["pending", "Cần dựng lại"];
  return vs.composed ? ["done", "Đã ghép"] : ["dirty", "Chưa ghép"];
};

export default function ResultView({ project, busy, version, beginAction, afterAction, onChange, onEdit }: Props) {
  const [voices, setVoices] = useState<{ id: string; label: string }[]>([]);
  const [newVoice, setNewVoice] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.voices().then(setVoices).catch(() => {}); }, []);
  const v = project.versions.find((x) => x.id === project.active_version) ?? project.versions[0];
  if (!v) return null;
  const run = async (f: () => Promise<unknown>) => {
    setErr(""); beginAction();
    try { await f(); afterAction(); } catch (e) { setErr((e as Error).message); }
  };
  const dirty = project.scenes.filter((s) => !v.scenes[s.id]?.composed).length;
  const scene = project.scenes.find((s) => s.id === editing);
  return (
    <div>
      <div className="versions" role="tablist" aria-label="Phiên bản">
        {project.versions.map((x) => (
          <button key={x.id} role="tab" aria-selected={x.id === v.id} className={x.id === v.id ? "tab on" : "tab"}
            disabled={busy} onClick={() => run(async () => onChange(await api.setActive(project.id, x.id)))}>{x.label}</button>
        ))}
        <span className="new-version">
          <select aria-label="Giọng cho bản mới" value={newVoice} onChange={(e) => setNewVoice(e.target.value)}>
            <option value="">Chọn giọng…</option>
            {voices.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
          <button disabled={busy || !newVoice} onClick={() => run(() => api.newVersion(project.id, newVoice))}>+ Bản mới với giọng này</button>
        </span>
      </div>
      {err && <div className="error">{err}</div>}
      {project.job_error && <div className="error">{project.job_error}</div>}
      {(dirty > 0 || !v.final) && (project.stage === "done" || project.stage === "images") && (
        <div className="warn row between">
          <span>{v.final ? `Có ${dirty} cảnh đã sửa, chưa ghép vào video.` : "Bản này chưa có video ghép."}</span>
          <button className="primary" disabled={busy} onClick={() => run(() => api.compose(project.id, v.id))}>Ghép lại</button>
        </div>
      )}
      {v.final && (
        <div className="card">
          <video controls src={api.file(project.id, v.final, `${v.id}-${version}`)} className={project.settings.aspect === "9:16" ? "portrait" : ""} />
          <div className="row">
            <a className="primary button" href={api.file(project.id, v.final)} download={`${project.title} - ${v.label}.mp4`}>Tải MP4</a>
            <button disabled={busy} onClick={() => onEdit("scenes")}>Sửa kịch bản / chia cảnh</button>
            <button disabled={busy} onClick={() => onEdit("images")}>Duyệt lại ảnh</button>
          </div>
        </div>
      )}
      <h2>Các cảnh · {v.label}</h2>
      <div className={`thumbs ${project.settings.aspect === "9:16" ? "portrait" : ""}`}>
        {project.scenes.map((s) => {
          const vs = v.scenes[s.id]; const [cls, text] = badge(vs);
          const base = `versions/${v.id}/scenes/${s.id}`;
          return (
            <div className="card" key={s.id}>
              <div className="row between"><b>Cảnh {s.id}</b><span className={`badge ${cls}`}>{text}</span></div>
              {vs?.status.draw === "done"
                ? <CaptionedPreview pid={project.id} base={base} bust={`${vs.duration_ms}-${vs.composed}-${version}-${s.text.length}`}
                    poster={api.file(project.id, `scenes/${s.id}/image.png`)} />
                : <img src={api.file(project.id, `scenes/${s.id}/image.png`)} alt={`Ảnh cảnh ${s.id}`} />}
              {vs?.voice && <span className="model-tag">Giọng riêng: {vs.voice}</span>}
              {vs?.error && <p className="small error">{vs.error}</p>}
              <div className="row">
                <button disabled={busy} onClick={() => setEditing(s.id)}>Sửa</button>
                {cls === "pending" && <button disabled={busy} onClick={() => run(() => api.rebuildScene(project.id, v.id, s.id))}>Dựng lại</button>}
              </div>
            </div>
          );
        })}
      </div>
      {scene && <SceneEditor project={project} version={v} scene={scene} busy={busy} voices={voices}
        onClose={() => setEditing(null)} beginAction={beginAction} afterAction={afterAction} onSaved={onChange} />}
    </div>
  );
}
