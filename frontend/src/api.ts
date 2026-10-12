export type Element = { label: string; say: string };
export type StepState = "pending" | "running" | "done" | "error";
export type Scene = { id: string; text: string; key_idea: string; visual_description: string; elements: Element[];
  image_prompt: string; status: Record<"image" | "voice" | "draw", StepState>; error: string | null; duration_ms: number | null };
export type Settings = { aspect: "16:9" | "9:16"; voice: string; captions: boolean; music: boolean; music_file: string | null };
export type Project = { id: string; title: string; created_at: string; settings: Settings; source_text: string;
  stage: "input" | "scenes" | "images" | "rendering" | "done"; scenes: Scene[]; final: string | null; job_error: string | null; timings?: Record<string, number> };
export type JobState = { busy: boolean; pid: string | null; kind: string | null; started_at: number | null; progress: JobEvent | null };
export type JobEvent = { pid: string; type: "progress" | "done" | "error"; msg: string; pct: number };

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))).detail;
    const msg = Array.isArray(d) ? d.map((x: { msg?: string }) => x?.msg ?? JSON.stringify(x)).join("; ") : d;
    throw new Error(msg || res.statusText);
  }
  return res.json();
}
export const api = {
  voices: () => j<{ id: string; label: string }[]>(fetch("/api/voices")),
  health: () => j<{ checks: { name: string; ok: boolean; hint: string }[] }>(fetch("/api/health")),
  list: () => j<Project[]>(fetch("/api/projects")),
  get: (id: string) => j<Project>(fetch(`/api/projects/${id}`)),
  create: (fd: FormData) => j<Project>(fetch("/api/projects", { method: "POST", body: fd })),
  saveScenes: (id: string, scenes: Scene[]) => j<Project>(fetch(`/api/projects/${id}/scenes`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(scenes) })),
  approveScenes: (id: string) => j(fetch(`/api/projects/${id}/approve/scenes`, { method: "POST" })),
  regenerate: (id: string, sid: string, image_prompt?: string) => j(fetch(`/api/projects/${id}/scenes/${sid}/regenerate`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_prompt }) })),
  segment: (id: string) => j(fetch(`/api/projects/${id}/segment`, { method: "POST" })),
  jobs: () => j<JobState>(fetch("/api/jobs")),
  render: (id: string) => j(fetch(`/api/projects/${id}/render`, { method: "POST" })),
  file: (id: string, path: string, bust = "") => `/api/projects/${id}/files/${path}${bust ? `?v=${bust}` : ""}`,
  events: (id: string, on: (e: JobEvent) => void, onOpen?: () => void) => {
    const es = new EventSource(`/api/projects/${id}/events`);
    es.onopen = () => onOpen?.();
    es.onmessage = (m) => on(JSON.parse(m.data));
    return () => es.close();
  },
};
