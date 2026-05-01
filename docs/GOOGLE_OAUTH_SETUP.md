# Google OAuth Login Setup

> Cho phép user "Đăng nhập với Google" thay vì tạo username/password.

## 1. Tạo OAuth 2.0 Client ID trên GCP

1. Vào <https://console.cloud.google.com/apis/credentials>
2. Chọn project (cùng project với Document AI / Vision càng tốt)
3. Bấm **+ CREATE CREDENTIALS** → **OAuth client ID**
4. Nếu lần đầu: phải tạo **OAuth consent screen**:
   - User Type: **External** (hoặc Internal nếu Google Workspace)
   - App name: `VIC OCR`
   - User support email: email của bạn
   - Authorized domains: `vkesys.com`
   - Developer contact: email
   - Scopes: bấm **ADD OR REMOVE SCOPES**, thêm `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`
   - Test users: thêm các Gmail của bạn nếu app ở mode Testing
5. Quay lại Credentials → CREATE CREDENTIALS → OAuth client ID
6. Application type: **Web application**
7. Name: `VIC OCR Web`
8. **Authorized JavaScript origins**:
   ```
   https://orc.vkesys.com
   http://localhost:8000
   ```
9. **Authorized redirect URIs**:
   ```
   https://orc.vkesys.com/auth/google/callback
   http://localhost:8000/auth/google/callback
   ```
10. Bấm **CREATE** → modal hiển thị **Client ID** + **Client secret**. Copy cả 2.

## 2. Cập nhật `.env`

```ini
GOOGLE_OAUTH_CLIENT_ID=123456789-abcdef.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx
# Optional override; nếu để trống thì auto từ url_for
OAUTH_REDIRECT_URI=https://orc.vkesys.com/auth/google/callback
```

Restart app:
```cmd
stop.bat
start.bat
```

Console khởi động sẽ in:
```
INFO oauth: Google OAuth: registered (client_id=12345678901-...)
```

Nếu thấy `Google OAuth: not configured (skipping)` → kiểm tra .env.

## 3. Test

1. Mở <https://orc.vkesys.com/auth/login>
2. Sẽ thấy nút **"Đăng nhập với Google"** dưới form login (chỉ hiện khi config OAuth có)
3. Click → redirect Google → chấp nhận quyền → quay về VIC OCR đã đăng nhập

## 4. Cách hệ thống xử lý

### User mới (chưa có account):
- Tạo User record:
  - `username` = local-part của email (vd `phuongpham3141@gmail.com` → `phuongpham3141`). Nếu trùng, suffix thêm số.
  - `email` = email từ Google
  - `oauth_provider` = `"google"`, `oauth_uid` = Google `sub` (id duy nhất)
  - `password` = random 24 chars (user có thể đổi sau)
  - `role` = `"user"` (admin phải set thủ công)
  - `avatar_url` = URL ảnh profile
  - `api_token` = sinh tự động

### User đã có account (cùng email):
- Link account hiện có với Google (set `oauth_provider`, `oauth_uid`)
- User có thể đăng nhập bằng cả password hoặc Google

### User bị `is_active=false`:
- Reject login với message "Tài khoản đã bị khoá"

## 5. Bảo mật

- **CSRF**: OAuth callback exempt khỏi CSRF (do redirect từ Google không có token)
- **State parameter**: Authlib tự handle (chống CSRF cho OAuth flow)
- **Session cookie**: HttpOnly, SameSite=Lax (xem `app/config.py`)
- **Token không lưu**: chỉ user info; không cache access_token

## 6. Troubleshooting

| Lỗi | Cách fix |
|---|---|
| `redirect_uri_mismatch` | URL trong `.env` không khớp với GCP. Phải MATCH chính xác (kể cả http vs https, port) |
| `Access blocked: Authorization Error` | App ở mode Testing nhưng email chưa thêm vào Test users. Vào OAuth consent screen → Test users → ADD USERS |
| `invalid_client` | Client ID/Secret sai hoặc client đã bị xoá |
| `Tài khoản đã bị khoá` | Admin đã set `is_active=false` cho user này. Vào /admin/users để mở khoá |
| Nút Google không hiện | Backend log "Google OAuth: not configured (skipping)" → kiểm tra .env có CLIENT_ID + CLIENT_SECRET không |

## 7. Production checklist

- [ ] OAuth Consent Screen status: **In production** (không phải Testing)
- [ ] App verification: nếu cần > 100 users, phải verify với Google
- [ ] HTTPS bắt buộc cho production redirect URI
- [ ] Privacy Policy URL trong Consent Screen (ít nhất 1 URL public)
- [ ] Logo app (120×120 px PNG) — optional, đẹp hơn
