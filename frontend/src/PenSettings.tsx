import { useEffect, useState } from "react";

const COLORS = [
  { id: "#1f1f1f", label: "Đen" },
  { id: "#1f5bff", label: "Xanh dương" },
  { id: "#e5484d", label: "Đỏ" },
  { id: "#0e9f78", label: "Xanh lá" },
  { id: "#7c5cff", label: "Tím" },
];

// Text printed on the drawing hand's marker, with a live preview of the hand.
export default function PenSettings({ text, color, onChange, names }:
  { text: string; color: string; onChange: (text: string, color: string) => void; names?: { text: string; color: string } }) {
  const [shown, setShown] = useState({ text, color });
  useEffect(() => {                       // debounce preview requests while typing
    const t = setTimeout(() => setShown({ text, color }), 400);
    return () => clearTimeout(t);
  }, [text, color]);
  const src = `/api/hand?text=${encodeURIComponent(shown.text)}&color=${encodeURIComponent(shown.color)}`;
  return (
    <div className="pen">
      <img className="pen-preview" src={src} alt="" />
      <div className="pen-zoom" role="img" aria-label={shown.text ? `Bút có chữ ${shown.text}` : "Bút trơn"}
        style={{ backgroundImage: `url("${src}")` }} />
      <div className="pen-fields">
        <label>Chữ trên thân bút (để trống = bút trơn)
          <input name={names?.text} value={text} maxLength={40} placeholder="VD: tên kênh của bạn"
            onChange={(e) => onChange(e.target.value, color)} />
        </label>
        <div className="pen-colors" role="radiogroup" aria-label="Màu chữ">
          {COLORS.map((c) => (
            <button type="button" key={c.id} role="radio" aria-checked={color === c.id} aria-label={c.label} title={c.label}
              className={color === c.id ? "swatch on" : "swatch"} style={{ background: c.id }}
              onClick={() => onChange(text, c.id)} />
          ))}
          {names && <input type="hidden" name={names.color} value={color} />}
        </div>
      </div>
    </div>
  );
}
