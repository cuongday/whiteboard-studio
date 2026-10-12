# Whiteboard Studio

Ứng dụng web chạy cục bộ: biến kịch bản tiếng Việt thành video whiteboard (ảnh minh hoạ do Gemini tạo, giọng đọc VieNeu-TTS, nét vẽ tay animate, phụ đề, nhạc nền).

## Yêu cầu

- Python >= 3.10
- Node >= 18
- ffmpeg (có `ffprobe`) trong PATH
- gcloud CLI

## Xác thực Google Cloud (Vertex AI)

```bash
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com   # bật Vertex AI API cho project
cp .env.example .env                               # rồi sửa giá trị
```

Cấu hình đặt trong file `.env` ở gốc repo (đã gitignore; biến môi trường thật được ưu tiên hơn):

```dotenv
GOOGLE_CLOUD_PROJECT=ten-project-cua-ban
GOOGLE_IMAGE_LOCATION=global          # vùng gọi Gemini (chia cảnh + tạo ảnh)
GOOGLE_VIDEO_LOCATION=us-central1     # dự phòng cho model video sau này
ADC_HOST_PATH=/home/<user>/.config/gcloud/application_default_credentials.json
```

`ADC_HOST_PATH` được gán vào `GOOGLE_APPLICATION_CREDENTIALS` khi khởi động.

Biến tuỳ chọn khác:

| Biến | Mặc định |
|---|---|
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` (model chia cảnh mặc định; chọn được trong giao diện) |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` (model tạo ảnh mặc định; chọn được trong giao diện) |
| `VIENEU_MODE` | `v3turbo` |
| `STUDIO_PROJECTS_DIR` | thư mục `projects/` ở gốc repo |

## Cài đặt và chạy

```bash
make setup   # tạo .venv, cài Python + npm (composer, frontend)
make run     # build frontend rồi chạy server -> http://localhost:8010
```

Cổng mặc định là 8010; đổi bằng `make run PORT=9000`. Chế độ phát triển: `make dev` (uvicorn có reload + Vite). Chạy test: `make test`.

## Quy trình sử dụng

1. Tạo dự án, dán kịch bản, chọn tỉ lệ khung hình, giọng, phụ đề, nhạc nền.
2. Gemini tách kịch bản thành các cảnh (câu thoại, mô tả, phần tử cần vẽ).
3. **Cổng duyệt 1**: xem và chỉnh các cảnh, sau đó duyệt để sinh ảnh.
4. Sinh ảnh cho từng cảnh.
5. **Cổng duyệt 2**: xem ảnh (tạo lại ảnh nào chưa ưng), duyệt để render.
6. Hệ thống tổng hợp giọng, tính thời điểm vẽ, vẽ tay từng cảnh và ghép bằng Remotion thành `final.mp4`.

## Cấu trúc dữ liệu

Mọi thứ nằm dưới `projects/<id>/`: `project.json`, thư mục từng cảnh (ảnh, wav, `words.json`, clip vẽ) và `final.mp4`. Kết quả từng cảnh được cache nên chỉ cảnh thay đổi mới bị làm lại.

## Xử lý sự cố

- **Lỗi ADC / credentials**: chạy lại `gcloud auth application-default login`, kiểm tra `GOOGLE_CLOUD_PROJECT`/`ADC_HOST_PATH` trong `.env` và đã bật `aiplatform.googleapis.com`.
- **Lần đầu dùng VieNeu** mất khoảng 20-40 giây để tải model.
- **Lần render đầu tiên**: Remotion tải Chrome headless nên lâu hơn bình thường và cần mạng.
- **Cổng bị chiếm**: đổi `PORT` (Makefile) và target proxy trong `frontend/vite.config.ts`.

## Ghi công

Mã vẽ tay trong `studio/vendor/` dựa trên [geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation) (MIT) và [vansyson1308/srt-whiteboard-animation](https://github.com/vansyson1308/srt-whiteboard-animation). Giấy phép: `studio/vendor/LICENSE-geeklee`, `studio/vendor/LICENSE-vansyson`.
