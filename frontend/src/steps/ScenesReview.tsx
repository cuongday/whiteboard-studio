import { useState } from "react";
import { api, Element, Project, Scene } from "../api";

const blank = (): Scene => ({ id: "new", text: "", key_idea: "", visual_description: "", elements: [], image_prompt: "",
  status: { image: "pending", voice: "pending", draw: "pending" }, error: null, duration_ms: null, narration: "" });

type Row = { s: Scene; raw: string };
const fmt = (els: Element[]) => els.map((e) => `${e.label} | ${e.say}`).join("\n");
const parse = (raw: string): Element[] => raw.split("\n").filter((l) => l.trim()).map((l) => {
  const [label, say = ""] = l.split("|").map((x) => x.trim()); return { label, say }; });
const mk = (s: Scene): Row => ({ s, raw: fmt(s.elements) });
const commit = (r: Row): Scene => ({ ...r.s, elements: parse(r.raw) });

type Props = { project: Project; busy: boolean; onChange: (p: Project) => void; beginAction: () => void; afterAction: () => void };

export default function ScenesReview({ project, busy, onChange, beginAction, afterAction }: Props) {
  const [rows, setRows] = useState<Row[]>(() => project.scenes.map(mk));
  const [msg, setMsg] = useState("");
  const setS = (i: number, patch: Partial<Scene>) => setRows(rows.map((r, k) => (k === i ? { ...r, s: { ...r.s, ...patch } } : r)));
  const setRaw = (i: number, raw: string) => setRows(rows.map((r, k) => (k === i ? { ...r, raw } : r)));
  const blur = (i: number) => setRows(rows.map((r, k) => (k === i ? { ...r, s: commit(r) } : r)));
  const merge = (i: number) => {
    const cur = rows.map((r) => commit(r)); const a = cur[i], b = cur[i + 1];
    const m = { ...a, id: "new", text: `${a.text} ${b.text}`, elements: [...a.elements, ...b.elements],
      visual_description: `${a.visual_description}; ${b.visual_description}` };
    setRows([...cur.slice(0, i), m, ...cur.slice(i + 2)].map(mk));
  };
  const split = (i: number) => {
    const cur = rows.map((r) => commit(r)); const s = cur[i]; const cut = s.text.indexOf(". ", s.text.length / 2);
    if (cut < 0) return;
    setRows([...cur.slice(0, i), { ...s, id: "new", text: s.text.slice(0, cut + 1) },
      { ...blank(), text: s.text.slice(cut + 2), visual_description: s.visual_description, elements: s.elements }, ...cur.slice(i + 1)].map(mk));
  };
  async function save(approve: boolean) {
    beginAction(); setMsg("");
    try {
      const p = await api.saveScenes(project.id, rows.map(commit));
      setRows(p.scenes.map(mk));
      if (approve) { await api.approveScenes(project.id); setMsg("Đang tạo ảnh…"); afterAction(); }
      onChange(p);
    } catch (e) { setMsg(String((e as Error).message)); }
  }
  const words = (t: string) => t.split(/\s+/).filter(Boolean).length;
  return (
    <div>
      <h2>Duyệt chia cảnh ({rows.length} cảnh)</h2>
      {rows.map((r, i) => (
        <div className="card scene" key={i}>
          <div className="row between"><b>Cảnh {i + 1}</b><span className="muted">~{Math.round(words(r.s.text) / 4)} giây</span></div>
          <label>Lời đọc<textarea rows={4} value={r.s.text} onChange={(e) => setS(i, { text: e.target.value })} /></label>
          <label>Mô tả hình (EN)<textarea rows={2} value={r.s.visual_description} onChange={(e) => setS(i, { visual_description: e.target.value })} /></label>
          <label>Đối tượng vẽ — mỗi dòng: <code>label | cụm từ kích hoạt</code>
            <textarea rows={3} value={r.raw} onChange={(e) => setRaw(i, e.target.value)} onBlur={() => blur(i)} />
          </label>
          <div className="row">
            {i < rows.length - 1 && <button type="button" onClick={() => merge(i)}>Gộp với cảnh sau</button>}
            <button type="button" onClick={() => split(i)}>Tách đôi</button>
            <button type="button" className="danger" onClick={() => setRows(rows.filter((_, k) => k !== i))}>Xoá</button>
          </div>
        </div>
      ))}
      <div className="row sticky">
        <button type="button" onClick={() => setRows([...rows, mk(blank())])}>+ Thêm cảnh</button>
        <button type="button" disabled={busy} onClick={() => save(false)}>Lưu</button>
        <button type="button" className="primary" disabled={busy} onClick={() => save(true)}>Duyệt → Tạo ảnh</button>
        <span className="muted">{msg}</span>
      </div>
    </div>
  );
}
