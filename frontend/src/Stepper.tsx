const STEPS = [
  { key: "input", label: "Kịch bản" },
  { key: "scenes", label: "Duyệt cảnh" },
  { key: "images", label: "Duyệt ảnh" },
  { key: "rendering", label: "Render" },
  { key: "done", label: "Video" },
];

export default function Stepper({ stage }: { stage: string }) {
  const at = STEPS.findIndex((s) => s.key === stage);
  return (
    <ol className="stepper" aria-label="Tiến trình dự án">
      {STEPS.map((s, i) => (
        <li key={s.key} className={i < at ? "past" : i === at ? "now" : ""} aria-current={i === at ? "step" : undefined}>
          <span className="dot">{i < at ? "✓" : i + 1}</span>{s.label}
        </li>
      ))}
    </ol>
  );
}
