import { api, Project } from "../api";
import { stepLabel } from "../labels";

export default function RenderView({ project, busy, version, onRefresh, onEdit }:
  { project: Project; busy: boolean; version: number; onRefresh: () => void; onEdit: (m: "scenes" | "images") => void }) {
  return (
    <div>
      <h2>Bước 3 · {project.stage === "done" ? "Hoàn tất" : "Đang render"}</h2>
      <table className="status">
        <thead><tr><th>Cảnh</th><th>Giọng</th><th>Vẽ</th><th>Thời lượng</th><th>Lỗi</th></tr></thead>
        <tbody>{project.scenes.map((s) => (
          <tr key={s.id}><td>{s.id}</td><td className={s.status.voice}>{stepLabel(s.status.voice)}</td><td className={s.status.draw}>{stepLabel(s.status.draw)}</td>
            <td>{s.duration_ms ? (s.duration_ms / 1000).toFixed(1) + "s" : ""}</td><td className="small">{s.error}</td></tr>))}
        </tbody>
      </table>
      {project.stage === "done" && project.final && (
        <div className="card">
          <video controls src={api.file(project.id, project.final, `${project.created_at}-${version}`)} className={project.settings.aspect === "9:16" ? "portrait" : ""} />
          <a className="primary button" href={api.file(project.id, project.final)} download={`${project.title}.mp4`}>Tải MP4</a>
        </div>
      )}
      <div className="row">
        <button onClick={onRefresh}>Làm mới</button>
        {project.stage === "done" && <>
          <button disabled={busy} onClick={() => onEdit("scenes")}>← Sửa cảnh</button>
          <button disabled={busy} onClick={() => onEdit("images")}>← Sửa ảnh</button>
        </>}
      </div>
    </div>
  );
}
