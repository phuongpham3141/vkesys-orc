# Document AI Layout Parser & Gemini API — Setup

Hai engine "cao cấp" cho tài liệu phức tạp (bảng, financial reports, layout
nhiều cột) khi mà OCR cơ bản (Tesseract / Vision) không xử lý nổi.

| Engine | Strength | Cost (tham khảo) |
|---|---|---|
| **Document AI Layout Parser** | Hiểu cấu trúc tài liệu: section, heading, table, list. Trả về JSON chứa từng layout block. | ~$10 / 1,000 trang |
| **Gemini Multimodal** | Hiểu ngữ nghĩa, có thể đọc bảng phức tạp + chart, output Markdown. Tốc độ nhanh. | ~$1.25 / 1M input tokens (Pro), $0.075 / 1M (Flash) |

---

## A. Document AI Layout Parser

### 1. Bật API

1. Vào <https://console.cloud.google.com> với project đã có (hoặc tạo mới —
   xem [GOOGLE_VISION_SETUP.md](GOOGLE_VISION_SETUP.md) bước 1).
2. **APIs & Services → Library** → tìm **"Document AI API"** → **ENABLE**.

### 2. Tạo Layout Parser Processor

1. Mở **Document AI** trong menu (hoặc trực tiếp
   <https://console.cloud.google.com/ai/document-ai/processors>).
2. Bấm **+ CREATE PROCESSOR**.
3. Trong danh sách, chọn **Layout Parser**:
   ![Layout Parser](https://cloud.google.com/document-ai/docs/images/layout-parser.png)
4. Đặt tên (vd: `vic-ocr-layout`), chọn **Region**:
   - `us` — multi-region, latency thấp ở Mỹ
   - `eu` — multi-region, latency thấp ở EU
   - `asia-northeast1` — Tokyo (gần VN nhất)
5. **CREATE**.
6. Sau khi tạo xong, copy **Processor ID** (đoạn cuối URL hoặc trên trang
   chi tiết processor — chuỗi ~16 ký tự hex).

### 3. Cấp quyền cho Service Account

Service Account đã tạo cho Vision (xem GOOGLE_VISION_SETUP.md) cần thêm role:

1. **IAM & Admin → IAM**.
2. Tìm Service Account của bạn (vd `vic-ocr-sa@...`), bấm **Edit**.
3. **Add another role** → tìm **Document AI API User** → **SAVE**.

### 4. Cấu hình trong VIC OCR

1. Đăng nhập VIC OCR → **Cài đặt → tab Document AI Layout**.
2. Nhập:
   - **GCP Project ID** (vd `vic-ocr-12345`)
   - **Location** (vd `us`)
   - **Processor ID** (chuỗi hex copy ở bước 2)
3. **Lưu cấu hình**.

> Service Account JSON dùng chung từ tab **Google Vision** — nếu chưa
> upload thì lên tab đó upload trước.

### 5. Test

Tải lên 1 PDF financial report, chọn engine **Document AI Layout** →
Bắt đầu OCR. Output sẽ có cấu trúc bảng + section preserved.

---

## B. Gemini Multimodal

### 1. Lấy API Key

Cách nhanh (ai cũng làm được, không cần GCP project):

1. Vào <https://aistudio.google.com/apikey>.
2. Đăng nhập tài khoản Google.
3. Bấm **Create API key** → chọn project (mặc định OK) → **Create**.
4. Copy key (bắt đầu bằng `AIza...`).

### 2. Cấu hình trong VIC OCR

1. **Cài đặt → tab Gemini Multimodal**.
2. Dán **Gemini API Key**.
3. **Gemini model** — để trống (mặc định `gemini-2.5-pro`) hoặc chọn:
   - `gemini-2.5-pro` — chất lượng cao nhất, chậm hơn, đắt hơn
   - `gemini-2.5-flash` — nhanh, rẻ, đủ cho hầu hết tài liệu
   - `gemini-2.5-flash-lite` — rẻ nhất
   - Model mới hơn (vd `gemini-3.1-pro` nếu project bạn có quyền truy cập)
4. **Lưu cấu hình**.

### 3. Test

Tải lên 1 PDF, chọn engine **Gemini Multimodal**. Gemini sẽ đọc PDF
trực tiếp (không cần convert sang ảnh), trả về Markdown có phân trang.

---

## So sánh 6 engine VIC OCR đang hỗ trợ

| Engine | Local/Cloud | Tốc độ | Bảng phức tạp | Cấu trúc tài liệu | Chi phí |
|---|---|---|---|---|---|
| Tesseract | Local | Chậm | ❌ | ❌ | Miễn phí |
| PaddleOCR | Local | Trung bình | △ | △ | Miễn phí |
| Google Vision | Cloud | Nhanh | ❌ | ❌ | Free 1k/tháng |
| Mistral OCR | Cloud | Nhanh | ✅ Markdown | △ | ~$1/1k trang |
| **Document AI Layout** | Cloud | Trung bình | ✅✅ | ✅✅ | ~$10/1k trang |
| **Gemini** | Cloud | Nhanh | ✅✅ | ✅✅ | $0.075–1.25/1M tokens |

**Khuyến nghị**:
- Tài liệu thông thường: **Tesseract** (miễn phí) hoặc **Google Vision**.
- Bảng phức tạp, financial report: **Mistral** hoặc **Document AI**.
- Tài liệu rất phức tạp + cần hiểu ngữ nghĩa (vd: extract số tiền theo dòng,
  link giữa text và bảng): **Gemini** hoặc **Document AI**.
- Tài liệu nhiều ngôn ngữ trộn lẫn: **Gemini**.
