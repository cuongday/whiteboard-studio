import { JobEvent, Project } from "./api";

// Progress derived from scene statuses in project.json — works even when the job
// runs in another server process, or the page was opened mid-job.
export function derivedProgress(p: Project): { msg: string; pct: number } | null {
  const n = p.scenes.length;
  if (!n) return null;
  const count = (step: "image" | "voice" | "draw") => p.scenes.filter((s) => s.status[step] === "done").length;
  const running = (step: "image" | "voice" | "draw") => p.scenes.filter((s) => s.status[step] === "running").map((s) => s.id);
  if (p.stage === "rendering") {
    const v = count("voice"), d = count("draw");
    const total = 2 * n + 1;                       // voices + draws + final compose
    const parts: string[] = [];
    const rv = running("voice"), rd = running("draw");
    if (rv.length) parts.push(`Đọc cảnh ${rv.join(", ")}`);
    if (rd.length) parts.push(`Vẽ cảnh ${rd.join(", ")}`);
    if (d === n) parts.push("Đang ghép video");
    return { msg: `${parts.join(" · ") || "Đang render"} — giọng ${v}/${n}, vẽ ${d}/${n}`, pct: (v + d) / total };
  }
  const ri = running("image");
  if (ri.length) return { msg: `Vẽ ảnh cảnh ${ri.join(", ")} — ${count("image")}/${n}`, pct: count("image") / n };
  return null;
}

export function pickProgress(ev: JobEvent | null, jobProgress: JobEvent | null, p: Project | null) {
  const live = ev?.type === "progress" ? ev : jobProgress;
  const derived = p ? derivedProgress(p) : null;
  // prefer the live message, but never show less than what the scene statuses prove is done
  if (live && derived) return { msg: live.msg, pct: Math.max(live.pct, derived.pct) };
  return live ?? derived;
}
