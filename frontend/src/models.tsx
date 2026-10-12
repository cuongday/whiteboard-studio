import { useEffect, useState } from "react";
import { api } from "./api";

export type ModelOpt = { id: string; label: string };
export type ModelList = { text: ModelOpt[]; image: ModelOpt[]; default_text: string; default_image: string };

let cache: Promise<ModelList> | null = null;

// Gemini models offered by the backend (fetched once per page load)
export function useModels(): ModelList | null {
  const [m, setM] = useState<ModelList | null>(null);
  useEffect(() => {
    cache ??= api.models();
    cache.then(setM).catch(() => { cache = null; });
  }, []);
  return m;
}

export function ModelSelect({ name, options, value, onChange, label }:
  { name?: string; options: ModelOpt[]; value: string; onChange?: (v: string) => void; label: string }) {
  return (
    <label>{label}
      <select name={name} value={value} onChange={(e) => onChange?.(e.target.value)}>
        {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  );
}
