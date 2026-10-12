import { useState } from "react";
import { api, Project, Scene } from "../api";

const blank = (): Scene => ({ id: "new", text: "", key_idea: "", visual_description: "", elements: [], image_prompt: "",
  status: { image: "pending", voice: "pending", draw: "pending" }, error: null, duration_ms: null });

export default function ScenesReview({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const [scenes, setScenes] = useState<Scene[]>(project.scenes);
  const [msg, setMsg] = useState("");
  const set = (i: number, patch: Partial<Scene>) => setScenes(scenes.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const merge = (i: number) => {
    const a = scenes[i], b = scenes[i + 1];
    const m = { ...a, id: "new", text: `${a.text} ${b.text}`, elements: [...a.elements, ...b.elements],
      visual_description: `${a.visual_description}; ${b.visual_description}` };
    setScenes([...scenes.slice(0, i), m, ...scenes.slice(i + 2)]);
  };
  const split = (i: number) => {
    const s = scenes[i]; const cut = s.text.indexOf(". ", s.text.length / 2);
    if (cut < 0) return;
    setScenes([...scenes.slice(0, i), { ...s, id: "new", text: s.text.slice(0, cut + 1) },
      { ...blank(), text: s.text.slice(cut + 2), visual_description: s.visual_description, elements: s.elements }, ...scenes.slice(i + 1)]);
  };
  async function save(approve: boolean) {
    try {
      const p = await api.saveScenes(project.id, scenes);
      if (approve) { await api.approveScenes(project.id); setMsg("Đang tạo ảnh…"); }
      onChange(p);
    } catch (e) { setMsg(String((e as Error).message)); }
  }
  const words = (t: string) => t.split(/\s+/).filter(Boolean).length;
  return (
    <div>
      <h2>Bước 1 · Duyệt chia cảnh ({scenes.length} cảnh)</h2>
      {scenes.map((s, i) => (
        <div className="card scene" key={i}>
          <div className="row between"><b>Cảnh {i + 1}</b><span className="muted">~{Math.round(words(s.text) / 4)} giây</span></div>
          <label>Lời đọc<textarea rows={4} value={s.text} onChange={(e) => set(i, { text: e.target.value })} /></label>
          <label>Mô tả hình (EN)<textarea rows={2} value={s.visual_description} onChange={(e) => set(i, { visual_description: e.target.value })} /></label>
          <label>Đối tượng vẽ — mỗi dòng: <code>label | cụm từ kích hoạt</code>
            <textarea rows={3} value={s.elements.map((e) => `${e.label} | ${e.say}`).join("\n")}
              onChange={(e) => set(i, { elements: e.target.value.split("\n").filter((l) => l.trim()).map((l) => {
                const [label, say = ""] = l.split("|").map((x) => x.trim()); return { label, say }; }) })} />
          </label>
          <div className="row">
            {i < scenes.length - 1 && <button type="button" onClick={() => merge(i)}>Gộp với cảnh sau</button>}
            <button type="button" onClick={() => split(i)}>Tách đôi</button>
            <button type="button" className="danger" onClick={() => setScenes(scenes.filter((_, k) => k !== i))}>Xoá</button>
          </div>
        </div>
      ))}
      <div className="row sticky">
        <button type="button" onClick={() => setScenes([...scenes, blank()])}>+ Thêm cảnh</button>
        <button type="button" onClick={() => save(false)}>Lưu</button>
        <button type="button" className="primary" onClick={() => save(true)}>Duyệt → Tạo ảnh</button>
        <span className="muted">{msg}</span>
      </div>
    </div>
  );
}
