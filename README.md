# 🍱 SchoolFood AI — v2.1

Nền tảng giám sát An toàn Thực phẩm bữa ăn học đường — dành cho Phụ Huynh, Ban Giám Sát, Y Tế Học Đường và Ban Giám Hiệu.

**Live:** [schoolfood-ai-vn.streamlit.app](https://schoolfood-ai-vn.streamlit.app)

## Tính năng

- 💬 **Hỏi đáp pháp luật ATTP** — AI trả lời dựa trên văn bản pháp luật Việt Nam
- ✅ **Checklist 20 điểm** — 3 cấp học, chuẩn NĐ 15/2018 · TTLT 13/2016 · QĐ 3958/2025
- 🔴 **Hệ thống cảnh báo 4 cấp** — CRITICAL / MAJOR / MINOR / ĐẠT CHUẨN
- 🩺 **Kiểm thực 3 bước** — Y Tế Học Đường, timestamp xác nhận từng bước
- 📸 **AI Vision** — Phân tích ảnh thực phẩm bằng Claude Sonnet 4.6
- 📅 **Lịch kiểm tra** — Nhắc nhở trước 15 phút theo từng vai trò, UTC+7
- 🚨 **Khẩn cấp ngộ độc** — Hướng dẫn xử lý + biên bản tự động
- 📄 **Xuất báo cáo Word** — Times New Roman, chuẩn hành chính Việt Nam
- 📊 **Dashboard lịch sử** — Biểu đồ Plotly: xu hướng, phân bố, theo tuần, top 10 fail
- 👥 **Phân quyền 4 vai trò** — Phụ Huynh view riêng (không checklist)

## Chạy local

```bash
pip install -r requirements.txt
streamlit run backend/regulatory_ai_prototype.py
```

## Cấu hình Supabase (tùy chọn — để dùng Dashboard lịch sử)

Thêm vào `.streamlit/secrets.toml`:
```toml
SUPABASE_URL = "https://..."
SUPABASE_ANON_KEY = "eyJ..."
```

## Căn cứ pháp lý

- NĐ 15/2018/NĐ-CP — Điều kiện ATTP bếp ăn tập thể
- TTLT 13/2016/TTLT-BYT-BGDĐT — Y tế trường học
- QĐ 3958/QĐ-BYT 2025 — Dinh dưỡng học đường
- QCVN 8-1, 8-2, 8-3:2011/BYT — Giới hạn ô nhiễm thực phẩm
