import { useEffect, useState } from "react";
import { api, Project } from "../api";
import { stageLabel } from "../labels";
import { ModelSelect, useModels } from "../models";

export default function NewProject({ list, onOpen, onCreated }: { list: Project[]; onOpen: (id: string) => void; onCreated: (p: Project) => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const models = useModels();
  const [textModel, setTextModel] = useState("");
  const [imageModel, setImageModel] = useState("");
  const [voices, setVoices] = useState<{ id: string; label: string }[]>([{ id: "Hải Đăng", label: "Hải Đăng" }]);
  useEffect(() => { api.voices().then((v) => v.length && setVoices(v)).catch(() => {}); }, []);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setErr(""); setBusy(true);
    const fd = new FormData(e.currentTarget);
    fd.set("captions", String(fd.get("captions") === "on"));
    fd.set("music", String(fd.get("music") === "on"));
    for (const k of ["file", "music_file"]) { const f = fd.get(k) as File | null; if (f && !f.name) fd.delete(k); }
    try { onCreated(await api.create(fd)); } catch (x) { setErr(String((x as Error).message)); } finally { setBusy(false); }
  }
  return (
    <div className="grid2">
      <form className="card" onSubmit={submit}>
        <h2>Dự án mới</h2>
        <label>Tên dự án<input name="title" placeholder="VD: Lạm phát là gì?" /></label>
        <label>Kịch bản<textarea name="text" rows={10} placeholder="Dán kịch bản vào đây…" /></label>
        <label>…hoặc tải file (.txt .docx .srt .pdf)<input type="file" name="file" accept=".txt,.docx,.srt,.pdf" /></label>
        <div className="row">
          <label>Tỉ lệ<select name="aspect"><option value="16:9">16:9 YouTube</option><option value="9:16">9:16 TikTok/Shorts</option></select></label>
          <label>Giọng VieNeu
            <select name="voice" defaultValue="Hải Đăng" key={voices.length}>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
        </div>
        {models && <div className="row">
          <ModelSelect name="text_model" label="Model chia cảnh (text)" options={models.text}
            value={textModel || models.default_text} onChange={setTextModel} />
          <ModelSelect name="image_model" label="Model tạo ảnh" options={models.image}
            value={imageModel || models.default_image} onChange={setImageModel} />
        </div>}
        <div className="row">
          <label className="check"><input type="checkbox" name="captions" defaultChecked /> Phụ đề karaoke</label>
          <label className="check"><input type="checkbox" name="music" /> Nhạc nền</label>
          <label className="music-file">File nhạc nền (.mp3 .wav .m4a…)<input type="file" name="music_file" accept="audio/*" /></label>
        </div>
        {err && <div className="error">{err}</div>}
        <button disabled={busy}>{busy ? "Đang tạo…" : "Tạo & chia cảnh"}</button>
      </form>
      <div className="card">
        <h2>Dự án gần đây</h2>
        {list.length === 0 && <p className="muted">Chưa có dự án.</p>}
        {list.map((p) => (
          <div key={p.id} className="listItem" onClick={() => onOpen(p.id)}>
            <b>{p.title}</b> <span className="muted">{p.settings.aspect} · {stageLabel(p.stage)} · {p.scenes.length} cảnh</span>
          </div>
        ))}
      </div>
    </div>
  );
}
