# HƯỚNG DẪN KẾT NỐI DATABASE — SUPABASE
## Bật tính năng Lịch sử, Lưu kết quả, Feedback

---

## Tại sao cần Supabase?

Hiện tại app **mất toàn bộ dữ liệu** khi tắt trình duyệt.
Sau khi kết nối Supabase:
- ✅ Mọi kết quả checklist được lưu vĩnh viễn
- ✅ Phụ Huynh gửi feedback → Ban Giám Hiệu nhận được
- ✅ Tab 📊 Lịch sử hiện đầy đủ dữ liệu
- ✅ Biểu đồ xu hướng theo tuần/tháng

---

## Bước 1 — Tạo tài khoản Supabase (miễn phí)

1. Vào **[supabase.com](https://supabase.com)** → Sign up bằng GitHub
2. **New Project**:
   - Name: `schoolfood-ai`
   - Database password: đặt mật khẩu mạnh (lưu lại)
   - Region: **Southeast Asia (Singapore)**
3. Chờ ~2 phút để project khởi tạo

---

## Bước 2 — Tạo database schema

1. Trong Supabase: vào **SQL Editor** → **New query**
2. Copy toàn bộ nội dung file `04_Development/sql/schema.sql`
3. Dán vào ô query → bấm **Run** (▶)
4. Kiểm tra: phải thấy thông báo "Success. No rows returned"

---

## Bước 3 — Lấy credentials

Trong Supabase: **Settings** → **API**:

| Thông tin | Vị trí |
|---|---|
| **Project URL** | "Project URL" → copy cả `https://xxx.supabase.co` |
| **Anon key** | "Project API keys" → "anon public" → copy |

---

## Bước 4 — Thêm vào Streamlit Cloud Secrets

**Trên Streamlit Cloud:**
1. Vào app → **⋮** → **Settings** → tab **Secrets**
2. Dán vào (thêm vào phần có ANTHROPIC_API_KEY):

```toml
ANTHROPIC_API_KEY  = "sk-ant-api03-..."   # Đã có sẵn
SUPABASE_URL       = "https://xxx.supabase.co"
SUPABASE_ANON_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

3. **Save** → app tự restart

**Để chạy local (không commit lên GitHub):**
Thêm vào `.streamlit/secrets.toml`:
```toml
SUPABASE_URL      = "https://xxx.supabase.co"
SUPABASE_ANON_KEY = "eyJ..."
```

---

## Bước 5 — Kiểm tra kết nối

Mở app → chọn tab **📊 Lịch sử**:
- Nếu thấy thông báo "Database chưa được kết nối" → kiểm tra lại secrets
- Nếu thấy "Chưa có dữ liệu lịch sử" → kết nối thành công! Thực hiện 1 checklist để test

---

## Xem và quản lý dữ liệu

Supabase cung cấp giao diện trực quan để xem dữ liệu:
- **Table Editor** → xem tất cả checklist đã lưu
- **SQL Editor** → query nâng cao
- **Dashboard** → stats tổng quan

---

## Chi phí

| Giai đoạn | Chi phí |
|---|---|
| Pilot < 10 trường | **$0** (free tier: 500MB DB, 1GB storage) |
| Scale 10-50 trường | **$25/tháng** (Pro plan) |
| > 50 trường | $25–$599/tháng (tùy quy mô) |

Free tier đủ dùng **1-2 năm** cho giai đoạn pilot với dữ liệu vừa phải.
