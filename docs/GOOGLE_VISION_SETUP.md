# Hướng dẫn lấy Google Cloud Vision API credentials

VIC OCR dùng Google Cloud Vision với **Service Account JSON**, không dùng API key
đơn giản. Free tier: 1,000 trang/tháng. Sau đây là 6 bước hoàn chỉnh.

---

## Bước 1 — Tạo Google Cloud Project

1. Vào <https://console.cloud.google.com> và đăng nhập tài khoản Google.
2. Click chọn project ở góc trên cùng → **NEW PROJECT**.
3. Đặt tên (ví dụ `vic-ocr`) → **CREATE**.
4. Sau khi tạo xong, đảm bảo bạn đã **chuyển sang project mới** ở thanh trên.

## Bước 2 — Bật Cloud Vision API

1. Mở menu trái → **APIs & Services → Library**
   (hoặc trực tiếp <https://console.cloud.google.com/apis/library>).
2. Gõ tìm **Cloud Vision API** → click vào.
3. Bấm **ENABLE**.

> Nếu được hỏi liên kết **Billing Account**, bạn cần thiết lập (free tier vẫn
> miễn phí 1,000 trang/tháng nhưng Google bắt buộc kết nối billing).

## Bước 3 — Tạo Service Account

1. Mở **APIs & Services → Credentials**
   (<https://console.cloud.google.com/apis/credentials>).
2. **CREATE CREDENTIALS → Service account**.
3. Service account name: `vic-ocr-sa` (tuỳ ý). Bấm **CREATE AND CONTINUE**.
4. Role: chọn **Cloud Vision → Cloud Vision AI Service Agent**
   (hoặc đơn giản hơn: **Project → Viewer** + sau đó cấp quyền Vision riêng).
   Bấm **CONTINUE → DONE**.

## Bước 4 — Tải file JSON key

1. Trong danh sách Service Accounts vừa tạo, click vào account.
2. Tab **KEYS → ADD KEY → Create new key → JSON → CREATE**.
3. Trình duyệt sẽ tự tải về file dạng `vic-ocr-xxxxx-yyyyyyyyy.json`.
4. **Bảo mật file này như mật khẩu** — không commit lên Git.

## Bước 5 — Đưa file vào VIC OCR

Có 2 cách, chọn **một**:

### Cách A — Cấu hình toàn hệ thống (admin)

1. Tạo thư mục `credentials/` trong root project (đã có sẵn, gitignored).
2. Copy file JSON vừa tải vào, đổi tên cho gọn:

   ```
   c:\vkesys-orc\credentials\google-vision.json
   ```

3. Chỉnh `.env`:

   ```ini
   GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-vision.json
   ```

4. Restart server. Engine **Google Vision** sẽ hiện "Sẵn sàng" cho mọi user
   (trừ khi user đã cấu hình riêng).

### Cách B — Cấu hình per-user qua giao diện

1. Đăng nhập vào VIC OCR.
2. Vào menu **Cài đặt** → tab **Google Cloud Vision**.
3. **Tải lên file JSON** (tự động lưu vào `credentials/userN_xxxx.json`)
   **hoặc** dán đường dẫn tuyệt đối tới file JSON đã có sẵn trên máy.
4. Bấm **Lưu cấu hình**. Engine sẽ chuyển sang trạng thái **Sẵn sàng**.

> **Cách B** ưu tiên hơn cách A — nếu user có config riêng, hệ thống dùng config
> đó. Nếu không, sẽ rơi về fallback `.env`.

## Bước 6 — Test

1. Vào **Tải lên** → kéo thả 1 file PDF.
2. Chọn **Google Vision** → **Bắt đầu OCR**.
3. Theo dõi tiến độ. Hoàn tất → xem kết quả từng trang.

---

## Một số lưu ý

| Lưu ý | Giải thích |
|---|---|
| Quota | Free 1,000 trang/tháng. Vượt quota → 7,5 USD / 1,000 trang. |
| Tiếng Việt | Vision tự nhận dạng — không cần `language_hints` (đã set sẵn `["vi","en"]`) |
| File JSON đã commit lên Git? | Xoá ngay, **revoke key** trên GCP, tạo key mới |
| Lỗi `permission denied` | Service Account thiếu role Vision — quay lại Bước 3 |
| Lỗi `billing not enabled` | Liên kết billing account, xem Bước 2 lưu ý |

---

## Tham khảo

- Tài liệu chính thức: <https://cloud.google.com/vision/docs/setup>
- Pricing: <https://cloud.google.com/vision/pricing>
- Service account: <https://cloud.google.com/iam/docs/service-account-overview>
