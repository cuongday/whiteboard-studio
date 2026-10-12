import { useEffect, useState } from "react";

const KIND_LABEL: Record<string, string> = { segment: "Chia cảnh", images: "Tạo ảnh", render: "Lồng tiếng & render",
  compose: "Ghép video", rebuild_scene: "Dựng lại cảnh", new_version: "Tạo bản mới" };

export const fmt = (s: number) => {
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

// Live elapsed time of the running job; shows the last run's duration otherwise.
export default function Timer({ startedAt, kind, timings }:
  { startedAt: number | null; kind: string | null; timings?: Record<string, number> }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!startedAt) return;
    const h = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(h);
  }, [startedAt]);

  if (startedAt) {
    return (
      <div className="timer live" role="timer" aria-live="off">
        <span className="timer-dot" />
        <span className="timer-label">{KIND_LABEL[kind ?? ""] ?? "Đang chạy"}</span>
        <span className="timer-value">{fmt(now - startedAt)}</span>
      </div>
    );
  }
  const done = Object.entries(timings ?? {});
  if (!done.length) return null;
  const total = done.reduce((a, [, v]) => a + v, 0);
  return (
    <div className="timer">
      {done.map(([k, v]) => <span key={k} className="timer-chip">{KIND_LABEL[k] ?? k} <b>{fmt(v)}</b></span>)}
      <span className="timer-chip total">Tổng <b>{fmt(total)}</b></span>
    </div>
  );
}
