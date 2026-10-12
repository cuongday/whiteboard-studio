export const STEP_LABEL: Record<string, string> = { pending: "Chờ", running: "Đang chạy", done: "Xong", error: "Lỗi" };
export const STAGE_LABEL: Record<string, string> = { input: "Đang chia cảnh", scenes: "Duyệt cảnh", images: "Duyệt ảnh", rendering: "Đang render", done: "Hoàn tất" };
export const stepLabel = (s: string) => STEP_LABEL[s] ?? s;
export const stageLabel = (s: string) => STAGE_LABEL[s] ?? s;
