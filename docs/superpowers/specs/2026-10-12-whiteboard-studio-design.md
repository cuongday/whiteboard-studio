# Whiteboard Studio — Design Spec (2026-10-12)

## Mục tiêu
Web app chạy local (1 người dùng, Linux, CPU) biến kịch bản thành video vẽ tay whiteboard tiếng Việt.

## Đầu vào & tuỳ chọn dự án
- Kịch bản: ô text hoặc upload `.txt`, `.docx`, `.srt`, `.pdf`.
- Tỉ lệ: `16:9` (cảnh ~20–35s) hoặc `9:16` (cảnh ~8–15s).
- Giọng VieNeu (preset, mặc định "Hải Đăng").
- Phụ đề karaoke: bật/tắt. Nhạc nền: bật/tắt + file upload (tự ducking dưới giọng).
- `.srt`: chỉ lấy văn bản; timestamp chỉ là gợi ý chia cảnh, giọng luôn đọc lại bằng VieNeu.

## Luồng
1. **Ingest** → văn bản thuần.
2. **Chia cảnh** — Gemini (Vertex AI qua ADC, `google-genai` `vertexai=True`), `response_schema`:
   `scenes[{text, key_idea, visual_description, elements[{label, say}]}]`. ⏸ **Duyệt**: sửa / gộp / tách / xoá cảnh.
3. **Ảnh** — Gemini image model qua ADC, prompt theo style guide geeklee (nền `#F5EBD7`, nét xám đậm, điểm nhấn đỏ/cam/xanh, không chữ), tỉ lệ theo dự án. Sau đó `auto_annotate` → `annotation.json`. ⏸ **Duyệt**: tạo lại ảnh từng cảnh (có thể sửa prompt).
4. **Giọng** — VieNeu v3 Turbo từng cảnh → `voice.wav` + word timings. `sceneDurationMs` = độ dài audio (+ đệm); `startMs` mỗi element = thời điểm cụm `say` được đọc (fallback: chia đều).
5. **Vẽ** — `render_stream_whiteboard.py` (geeklee, vendored) → `clip.mp4` không tiếng.
6. **Ghép** — Remotion: `Series` các clip + audio từng cảnh + Captions (tuỳ chọn) + Music với ducking (tuỳ chọn) → `final.mp4`.

Mọi bước cache theo cảnh; sửa 1 cảnh chỉ chạy lại cảnh đó và các bước sau của nó.

## Cấu trúc
```
whiteboard-studio/
├── backend/ (FastAPI, Python 3.11)
│   app.py · ingest.py · llm.py · voice.py · annotate.py · compose.py · jobs.py
│   whiteboard/  (vendored từ geeklee, MIT; auto_annotate + VieNeu wrapper lấy từ vansyson, giữ license)
├── composer/  (Remotion TS: FinalVideo, SceneClip, Captions, Music)
├── frontend/  (React + Vite: Nhập → Duyệt cảnh → Duyệt ảnh → Render/Tải)
└── projects/<id>/ project.json, uploads/, scenes/NN/{image.png, annotation.json, voice.wav, words.json, clip.mp4}, final.mp4
```
- `project.json` là nguồn sự thật: settings, scenes (nội dung + trạng thái từng bước), job hiện tại.
- `jobs.py`: 1 worker thread, một job tại một thời điểm; tiến độ đẩy qua SSE.
- API chính: `POST /projects`, `GET /projects/{id}`, `PUT /projects/{id}/scenes`, `POST .../scenes/{n}/regenerate-image`, `POST .../approve/{stage}`, `POST .../render`, `GET .../events` (SSE), `GET .../final.mp4`.

## Xử lý lỗi
- Trạng thái mỗi cảnh/bước: `pending|running|done|error(msg)`; lỗi cục bộ → nút "Thử lại" cho cảnh đó.
- Gemini: retry 2 lần khi JSON sai schema; backoff khi 429/5xx.
- Khởi động: kiểm tra ADC + `GOOGLE_CLOUD_PROJECT` (+ `GOOGLE_CLOUD_LOCATION`, mặc định `global`), ffmpeg, node/npx, vieneu; báo hướng dẫn cụ thể nếu thiếu.
- Model ID cấu hình qua biến môi trường (`GEMINI_TEXT_MODEL`, `GEMINI_IMAGE_MODEL`).

## Kiểm thử
- Unit: ingest 4 định dạng; validate schema chia cảnh; ánh xạ word timings → `startMs`; dựng props Remotion.
- E2E: mock Gemini + VieNeu (ảnh mẫu, wav im lặng) → video 2 cảnh; kiểm tra bằng ffprobe (thời lượng ≈ tổng audio, có luồng audio, đúng kích thước theo tỉ lệ).

## Ngoài phạm vi
Đa người dùng/đăng nhập, GPU, giọng engine khác, chỉnh annotation bằng tay trong UI (có thể thêm sau qua preview.html của geeklee).
