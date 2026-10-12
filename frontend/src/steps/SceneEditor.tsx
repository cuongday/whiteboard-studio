import { useState } from "react";
import { api, Element, Project, Scene, Version } from "../api";
import { ModelSelect, useModels } from "../models";

type Props = { project: Project; version: Version; scene: Scene; busy: boolean; voices: { id: string; label: string }[];
  onClose: () => void; beginAction: () => void; afterAction: () => void; onSaved: (p: Project) => void };

export default function SceneEditor({ project, version, scene, busy, voices, onClose, beginAction, afterAction, onSaved }: Props) {
  const vs = version.scenes[scene.id];
  const [text, setText] = useState(scene.text);
  const [narration, setNarration] = useState(scene.narration);
  const [voice, setVoice] = useState(vs?.voice ?? version.voice);
  const [els, setEls] = useState<Element[]>(scene.elements);
  const [imageModel, setImageModel] = useState(scene.image_model ?? project.settings.image_model);
  const [listenUrl, setListenUrl] = useState("");
  const [listening, setListening] = useState(false);
  const [err, setErr] = useState("");
  const models = useModels();

  const move = (i: number, d: number) => {
    const j = i + d; if (j < 0 || j >= els.length) return;
    const n = [...els]; [n[i], n[j]] = [n[j], n[i]]; setEls(n);
  };
  const listen = async () => {
    setErr(""); setListening(true);
    try { setListenUrl((await api.listen(project.id, scene.id, narration.trim() || text, voice)).url); }
    catch (e) { setErr((e as Error).message); } finally { setListening(false); }
  };
  const save = async () => {
    setErr(""); beginAction();
    try {
      let p = await api.editScene(project.id, scene.id, { text, narration, elements: els.filter((e) => e.label.trim()) });
      if ((vs?.voice ?? version.voice) !== voice) p = await api.setSceneVoice(project.id, version.id, scene.id, voice);
      onSaved(p);
      await api.rebuildScene(project.id, version.id, scene.id);
      afterAction(); onClose();
    } catch (e) { setErr((e as Error).message); }
  };
  const regen = async () => {
    setErr(""); beginAction();
    try { await api.regenerate(project.id, scene.id, undefined, imageModel); afterAction(); }
    catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label={`Sửa cảnh ${scene.id}`} onClick={(e) => e.stopPropagation()}>
        <div className="row between"><h2>Sửa cảnh {scene.id}</h2><button onClick={onClose} aria-label="Đóng">✕</button></div>
        {err && <div className="error">{err}</div>}
        {vs?.error && <div className="error">{vs.error}</div>}
        <label>Phụ đề (chữ hiện trên video)<textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label>Lời đọc (để trống = đọc đúng như phụ đề)
          <textarea rows={3} value={narration} placeholder={text} onChange={(e) => setNarration(e.target.value)} />
        </label>
        <div className="row">
          <label>Giọng cho cảnh này ({version.label})
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
          <button type="button" disabled={listening} onClick={listen}>{listening ? "Đang đọc…" : "Nghe thử"}</button>
        </div>
        {listenUrl && <audio controls autoPlay src={listenUrl} />}
        <h3>Ảnh</h3>
        <img className="drawer-img" src={api.file(project.id, `scenes/${scene.id}/image.png`, `${scene.image_model}-${scene.status.image}`)} alt={`Ảnh cảnh ${scene.id}`} />
        <div className="regen">
          {models && <ModelSelect label="Model tạo ảnh" options={models.image} value={imageModel} onChange={setImageModel} />}
          <button type="button" disabled={busy} onClick={regen}>Tạo lại ảnh</button>
        </div>
        <h3>Đối tượng vẽ (theo thứ tự)</h3>
        {els.map((e, i) => (
          <div className="el-row" key={i}>
            <input value={e.label} aria-label="Tên đối tượng" onChange={(x) => setEls(els.map((y, k) => (k === i ? { ...y, label: x.target.value } : y)))} />
            <input value={e.say} aria-label="Vẽ khi đọc tới" placeholder="vẽ khi đọc tới…" onChange={(x) => setEls(els.map((y, k) => (k === i ? { ...y, say: x.target.value } : y)))} />
            <button type="button" aria-label="Lên" onClick={() => move(i, -1)}>↑</button>
            <button type="button" aria-label="Xuống" onClick={() => move(i, 1)}>↓</button>
          </div>
        ))}
        <div className="row sticky">
          <button className="primary" disabled={busy} onClick={save}>Lưu & dựng lại cảnh</button>
          <span className="muted small">Sau khi dựng xong, bấm "Ghép lại" để cập nhật video.</span>
        </div>
      </aside>
    </div>
  );
}
