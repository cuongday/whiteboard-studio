export type Composer = "ffmpeg" | "remotion";

const OPTIONS: { id: Composer; label: string }[] = [
  { id: "ffmpeg", label: "ffmpeg — nhanh (~10 giây cho video 2 phút)" },
  { id: "remotion", label: "Remotion — chậm hơn nhiều (~5 phút cho video 2 phút)" },
];

export default function ComposerSelect({ value, onChange, name, label = "Ghép video bằng" }:
  { value: Composer; onChange?: (v: Composer) => void; name?: string; label?: string }) {
  return (
    <label>{label}
      <select name={name} value={value} onChange={(e) => onChange?.(e.target.value as Composer)}>
        {OPTIONS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  );
}
