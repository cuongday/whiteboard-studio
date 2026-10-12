import { useEffect, useState } from "react";
import { api } from "./api";

type W = { text: string; start_ms: number; end_ms: number };

// Scene preview video with the subtitle line shown under it (not burned into the video).
export default function CaptionedPreview({ pid, base, bust, poster, onMissing }: { pid: string; base: string; bust: string; poster?: string; onMissing?: () => void }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [bust]);
  const [words, setWords] = useState<W[]>([]);
  const [ms, setMs] = useState(0);
  useEffect(() => {
    fetch(api.file(pid, `${base}/words.json`, bust)).then((r) => (r.ok ? r.json() : [])).then(setWords).catch(() => setWords([]));
  }, [pid, base, bust]);
  const line: W[] = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (w.start_ms - 150 <= ms && ms <= w.end_ms + 400) {
      let a = i; while (a > 0 && !/[.!?…]$/.test(words[a - 1].text) && i - a < 6) a--;
      let b = i; while (b < words.length - 1 && !/[.!?…]$/.test(words[b].text) && b - a < 10) b++;
      line.push(...words.slice(a, b + 1)); break;
    }
  }
  if (failed) return (
    <div className="preview">
      {poster && <img src={poster} alt="" />}
      <p className="small muted">Chưa có bản xem thử — bấm Dựng lại</p>
    </div>
  );
  return (
    <div className="preview">
      <video controls preload="metadata" poster={poster} src={api.file(pid, `${base}/preview.mp4`, bust)}
        onError={() => { setFailed(true); onMissing?.(); }}
        onTimeUpdate={(e) => setMs(e.currentTarget.currentTime * 1000)} />
      <p className="preview-caption" aria-live="off">
        {line.map((w, k) => <span key={k} className={ms >= w.start_ms ? "on" : ""}>{w.text} </span>)}
      </p>
    </div>
  );
}
