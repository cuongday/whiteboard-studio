export type Element = { label: string; say: string };
export type StepState = "pending" | "running" | "done" | "error";
export type Scene = { id: string; text: string; key_idea: string; visual_description: string; elements: Element[];
  image_prompt: string; status: Record<"image" | "voice" | "draw", StepState>; error: string | null; duration_ms: number | null; image_model?: string | null; image_at?: number | null; narration: string };
export type Settings = { aspect: "16:9" | "9:16"; voice: string; captions: boolean; music: boolean; music_file: string | null;
  text_model: string; image_model: string; pen_text: string; pen_color: string; composer: "ffmpeg" | "remotion" };
export type Project = { id: string; title: string; created_at: string; settings: Settings; source_text: string;
  stage: "input" | "scenes" | "images" | "rendering" | "done"; scenes: Scene[]; final: string | null; job_error: string | null; timings?: Record<string, number>;
  versions: Version[]; active_version: string };
export type JobState = { busy: boolean; pid: string | null; kind: string | null; started_at: number | null; progress: JobEvent | null };
export type JobEvent = { pid: string; type: "progress" | "done" | "error" | "cancelled"; msg: string; pct: number };

const JSONH = { "Content-Type": "application/json" };

export type VersionScene = { voice: string | null; status: Record<"voice" | "draw", StepState>; error: string | null;
  duration_ms: number | null; composed: boolean; built_at?: number | null };
export type Version = { id: string; label: string; voice: string; created_at: string;
  scenes: Record<string, VersionScene>; final: string | null; timings: Record<string, number> };

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
  approveScenes: (id: string, opts?: { image_model?: string; all?: boolean }) => j(fetch(`/api/projects/${id}/approve/scenes`,
    { method: "POST", headers: JSONH, body: JSON.stringify(opts ?? {}) })),
  regenerate: (id: string, sid: string, image_prompt?: string, image_model?: string) => j(fetch(`/api/projects/${id}/scenes/${sid}/regenerate`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_prompt, image_model }) })),
  segment: (id: string, text_model?: string) => j(fetch(`/api/projects/${id}/segment`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text_model }) })),
  saveSettings: (id: string, settings: Settings) => j<Project>(fetch(`/api/projects/${id}/settings`,
    { method: "PUT", headers: JSONH, body: JSON.stringify(settings) })),
  models: () => j<import("./models").ModelList>(fetch("/api/models")),
  jobs: () => j<JobState>(fetch("/api/jobs")),
  deleteVersion: (id: string, vid: string) => j<Project>(fetch(`/api/projects/${id}/versions/${vid}`, { method: "DELETE" })),
  storage: (id: string) => j<{ total: number; cleanable: number }>(fetch(`/api/projects/${id}/storage`)),
  cleanup: (id: string) => j<{ total: number; cleanable: number }>(fetch(`/api/projects/${id}/cleanup`, { method: "POST" })),
  srt: (id: string, vid: string) => `/api/projects/${id}/versions/${vid}/subtitles.srt`,
  cancel: (id: string) => j(fetch(`/api/projects/${id}/cancel`, { method: "POST" })),
  render: (id: string) => j(fetch(`/api/projects/${id}/render`, { method: "POST" })),
  editScene: (id: string, sid: string, body: { text?: string; narration?: string; elements?: Element[] }) =>
    j<Project>(fetch(`/api/projects/${id}/scenes/${sid}`, { method: "PUT", headers: JSONH, body: JSON.stringify(body) })),
  setSceneVoice: (id: string, vid: string, sid: string, voice: string | null) =>
    j<Project>(fetch(`/api/projects/${id}/versions/${vid}/scenes/${sid}`, { method: "PUT", headers: JSONH, body: JSON.stringify({ voice }) })),
  rebuildScene: (id: string, vid: string, sid: string) =>
    j(fetch(`/api/projects/${id}/versions/${vid}/scenes/${sid}/rebuild`, { method: "POST" })),
  compose: (id: string, vid: string, composer?: "ffmpeg" | "remotion") => j(fetch(`/api/projects/${id}/versions/${vid}/compose`,
    { method: "POST", headers: JSONH, body: JSON.stringify({ composer }) })),
  newVersion: (id: string, voice: string) =>
    j(fetch(`/api/projects/${id}/versions`, { method: "POST", headers: JSONH, body: JSON.stringify({ voice }) })),
  setActive: (id: string, vid: string) =>
    j<Project>(fetch(`/api/projects/${id}/active_version`, { method: "PUT", headers: JSONH, body: JSON.stringify({ id: vid }) })),
  listen: (id: string, sid: string, narration: string, voice: string) =>
    j<{ url: string }>(fetch(`/api/projects/${id}/scenes/${sid}/listen`, { method: "POST", headers: JSONH, body: JSON.stringify({ narration, voice }) })),
  file: (id: string, path: string, bust = "") => `/api/projects/${id}/files/${path}${bust ? `?v=${bust}` : ""}`,
  events: (id: string, on: (e: JobEvent) => void, onOpen?: () => void) => {
    const es = new EventSource(`/api/projects/${id}/events`);
    es.onopen = () => onOpen?.();
    es.onmessage = (m) => on(JSON.parse(m.data));
    return () => es.close();
  },
};
