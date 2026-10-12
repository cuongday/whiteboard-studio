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
| `STUDIO_VOICE_WORKERS` | `4` (số bản VieNeu đọc song song, mỗi bản ~1,5 GB RAM) |
| `STUDIO_DRAW_WORKERS` | 3/8 số nhân CPU, tối đa 8 (số cảnh vẽ song song) |
| `STUDIO_FFMPEG_PRESET` | `veryfast` (preset x264 khi ghép bằng ffmpeg) |
| `STUDIO_FFMPEG_CRF` | `20` (chất lượng x264 khi ghép bằng ffmpeg; nhỏ hơn = nét hơn) |
| `STUDIO_RENDER_CONCURRENCY` | `50%` (số tab Chrome Remotion dùng khi ghép video) |
| `STUDIO_OFFTHREAD_CACHE_MB` | `1024` (bộ nhớ đệm khung hình của Remotion) |
| `STUDIO_RENDER_ATTEMPTS` | `2` (tự render lại khi gặp lỗi mạng/tải file tạm thời) |
| `STUDIO_IMAGE_WORKERS` | `4` (số ảnh Gemini tạo song song) |
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

## Ghép video: ffmpeg hoặc Remotion

Chọn ở form tạo dự án, hoặc ngay cạnh nút **Ghép lại** trên màn Kết quả:

- **ffmpeg** (mặc định): nối các clip, trộn giọng + nhạc nền (tự giảm khi có giọng), in phụ đề karaoke
  (ASS, font Be Vietnam Pro) trong một lượt mã hoá. Dự án 11 cảnh / 127 giây: ~16 giây.
- **Remotion**: dựng từng khung hình qua Chrome headless. Cùng dự án: ~5 phút. Giữ lại để so sánh
  hoặc khi cần hiệu ứng React.

## Bút vẽ

Bàn tay cầm bút trong video mặc định là bút trắng trơn. Ở form tạo dự án (hoặc mục **Bút vẽ** trên màn Kết quả)
nhập **chữ trên thân bút** (ví dụ tên kênh, tối đa 40 ký tự, hỗ trợ tiếng Việt) và chọn màu chữ; có xem trước ngay.
Đổi bút trên dự án đã render sẽ vẽ lại mọi cảnh (giữ nguyên giọng), sau đó bấm **Ghép lại**.
Ảnh bàn tay và script in chữ lấy từ vansyson/srt-whiteboard-animation (MIT); font Be Vietnam Pro (OFL, `studio/vendor/fonts/`).

## Sửa từng cảnh và phiên bản giọng

Sau khi render, màn **Kết quả** hiện video cuối và lưới các cảnh (clip xem thử + phụ đề).

- **Sửa** một cảnh: đổi phụ đề, viết **lời đọc** riêng (ví dụ phụ đề "API", lời đọc "ây pi ai") và bấm **Nghe thử**,
  đổi giọng riêng cho cảnh, tạo lại ảnh (chọn model), đổi thứ tự / cụm từ kích hoạt của các đối tượng vẽ.
  **Lưu & dựng lại cảnh** chỉ đọc + vẽ lại cảnh đó; sau đó bấm **Ghép lại** để cập nhật video.
- **+ Bản mới với giọng này**: tạo phiên bản video mới (Bản 2, Bản 3…) dùng chung nội dung, giữ nguyên các bản cũ.
  Sửa nội dung một cảnh áp dụng cho mọi bản (bản nào cũng hiện "Chưa ghép" cho tới khi ghép lại).
- Dữ liệu: `projects/<id>/versions/<vN>/` chứa giọng, clip, bản xem thử và `final.mp4` của từng bản.
  Dự án cũ tự chuyển thành "Bản 1" khi mở lần đầu.

## Cấu trúc dữ liệu

Mọi thứ nằm dưới `projects/<id>/`: `project.json`, thư mục từng cảnh (ảnh, wav, `words.json`, clip vẽ) và `final.mp4`. Kết quả từng cảnh được cache nên chỉ cảnh thay đổi mới bị làm lại.

## Xử lý sự cố

- **Remotion lỗi `ERR_NETWORK_CHANGED` / `Failed to fetch`**: Chrome mất kết nối tới server file nội bộ của Remotion khi card mạng ảo thay đổi (container Docker khởi động lại liên tục, VPN) hoặc khi máy hết RAM/swap. Tool tự thử lại 1 lần; nếu vẫn lỗi, giải phóng RAM, dừng container đang restart lặp, rồi bấm render lại.

- **Lỗi ADC / credentials**: chạy lại `gcloud auth application-default login`, kiểm tra `GOOGLE_CLOUD_PROJECT`/`ADC_HOST_PATH` trong `.env` và đã bật `aiplatform.googleapis.com`.
- **Lần đầu dùng VieNeu** mất khoảng 20-40 giây để tải model.
- **Lần render đầu tiên**: Remotion tải Chrome headless nên lâu hơn bình thường và cần mạng.
- **Cổng bị chiếm**: đổi `PORT` (Makefile) và target proxy trong `frontend/vite.config.ts`.

## Ghi công

Mã vẽ tay trong `studio/vendor/` dựa trên [geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation) (MIT) và [vansyson1308/srt-whiteboard-animation](https://github.com/vansyson1308/srt-whiteboard-animation). Giấy phép: `studio/vendor/LICENSE-geeklee`, `studio/vendor/LICENSE-vansyson`.
