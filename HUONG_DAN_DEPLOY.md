# HƯỚNG DẪN DEPLOY SCHOOLFOOD AI LÊN STREAMLIT CLOUD
## Miễn phí · Không cần server · Người dùng không cần nhập API key

---

## Tại sao dùng Streamlit Cloud?

- **Miễn phí** cho 1 app public
- **Không cần server** — Streamlit lo hết
- **API key ẩn trong Secrets** — người dùng không thấy, không cần nhập
- **URL đẹp** kiểu: `schoolfood-ai.streamlit.app`
- **Tự động cập nhật** khi bạn push code mới lên GitHub

---

## Bước 1 — Tạo tài khoản GitHub (nếu chưa có)

1. Vào [github.com](https://github.com) → Sign up
2. Dùng email nguyenthanhdanh3096@gmail.com
3. Tạo repository mới tên `schoolfood-ai` (chọn **Private** để bảo mật)

---

## Bước 2 — Upload code lên GitHub

Mở Terminal, chạy lần lượt từng lệnh:

```bash
cd /Users/nguyenthanhdanh/Desktop/ABI/SchoolFood_AI/04_Development

# Khởi tạo git
git init
git add .
git commit -m "SchoolFood AI v1.1 - initial deploy"

# Kết nối với GitHub (thay YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/schoolfood-ai.git
git branch -M main
git push -u origin main
```

> **Lưu ý:** Lệnh `git add .` sẽ bỏ qua `.streamlit/secrets.toml` (đã có trong .gitignore) → API key không bị lộ.

---

## Bước 3 — Deploy lên Streamlit Cloud

1. Vào [share.streamlit.io](https://share.streamlit.io)
2. Đăng nhập bằng tài khoản GitHub
3. Bấm **"New app"**
4. Điền thông tin:
   - **Repository:** `YOUR_USERNAME/schoolfood-ai`
   - **Branch:** `main`
   - **Main file path:** `backend/regulatory_ai_prototype.py`
5. Bấm **"Deploy!"**

---

## Bước 4 — Thêm API Key vào Secrets (QUAN TRỌNG)

Đây là bước để tất cả người dùng dùng được AI chat mà không cần nhập key:

1. Sau khi deploy, vào trang app → bấm **⋮ (3 chấm)** → **"Settings"**
2. Chọn tab **"Secrets"**
3. Dán nội dung sau vào ô:

```toml
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

*(Thay bằng API key thật của bạn từ console.anthropic.com)*

4. Bấm **"Save"** → app tự restart
5. Kiểm tra: sidebar hiển thị **"✅ AI đã kết nối"**

---

## Bước 5 — Chia sẻ URL

URL của bạn sẽ có dạng:
```
https://schoolfood-ai.streamlit.app
```

Gửi URL này cho:
- Thành viên Ban Giám Sát tại trường pilot
- Y Tế Học Đường
- Ban Giám Hiệu muốn xem demo

---

## Chi Phí

| Hạng mục | Chi phí |
|---------|---------|
| Streamlit Cloud hosting | **Miễn phí** |
| GitHub repository | **Miễn phí** |
| API cost (30 câu hỏi/ngày × $0.003) | ~**$2.7/tháng** |
| $5 credit ban đầu | Đủ dùng ~**1.8 tháng pilot** |

---

## Cập Nhật App Sau Khi Deploy

Mỗi khi sửa code, chỉ cần:

```bash
cd /Users/nguyenthanhdanh/Desktop/ABI/SchoolFood_AI/04_Development
git add .
git commit -m "Mô tả thay đổi"
git push
```

Streamlit Cloud tự động reload app trong ~1 phút.

---

## Nếu Gặp Lỗi Khi Deploy

**Lỗi "Module not found":**
→ Kiểm tra file `requirements.txt` đã đủ packages

**Lỗi "File not found":**
→ Kiểm tra đường dẫn Main file path đúng chưa

**AI không hoạt động:**
→ Kiểm tra Secrets đã có `ANTHROPIC_API_KEY` chưa
→ Kiểm tra key còn credit chưa tại console.anthropic.com

**Cần hỗ trợ:**
→ Streamlit Community Forum: discuss.streamlit.io
