import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

export type Word = { text: string; start_ms: number; end_ms: number };

// group words into lines of max ~7 words / maxChars (one row on screen), breaking after sentence punctuation
const lines = (words: Word[], maxChars: number) => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    if (cur.length && [...cur, w].map((x) => x.text).join(" ").length > maxChars) { out.push(cur); cur = []; }
    cur.push(w);
    if (cur.length >= 7 || /[.!?…]$/.test(w.text)) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
};

export const Captions: React.FC<{ words: Word[] }> = ({ words }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ms = (frame / fps) * 1000;
  const portrait = height > width;
  const line = lines(words, portrait ? 24 : 42).find((l) => ms >= l[0].start_ms - 100 && ms <= l[l.length - 1].end_ms + 300);
  if (!line) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: portrait ? 260 : 70 }}>
      <div style={{ background: "rgba(40,40,40,0.72)", borderRadius: 14, padding: "10px 22px", maxWidth: "86%",
        textAlign: "center", fontFamily: "Be Vietnam Pro, Arial, sans-serif", fontWeight: 700, fontSize: portrait ? 54 : 46, lineHeight: 1.3 }}>
        {line.map((w, i) => (
          <span key={i} style={{ color: ms >= w.start_ms ? "#FFC857" : "#FFFFFF" }}>{w.text} </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
