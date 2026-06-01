# 🍱 SchoolFood AI

Nền tảng giám sát An toàn Thực phẩm bữa ăn học đường — dành cho Phụ Huynh, Ban Giám Sát, Y Tế Học Đường và Ban Giám Hiệu.

## Tính năng

- 💬 **Hỏi đáp pháp luật ATTP** — AI trả lời dựa trên văn bản pháp luật Việt Nam
- ✅ **Checklist 20 điểm** — Chuẩn hoá theo NĐ 15/2018, TTLT 13/2016, QĐ 3958/2025
- 🔴 **Hệ thống cảnh báo** — CRITICAL / MAJOR / MINOR / ĐẠT CHUẨN
- 📅 **Lịch kiểm tra** — Nhắc nhở trước 15 phút theo từng vai trò
- 🚨 **Khẩn cấp** — Hướng dẫn xử lý ngộ độc từng bước
- 📄 **Xuất báo cáo** — File .txt gửi Ban Giám Hiệu

## Chạy local

```bash
pip install -r requirements.txt
streamlit run backend/regulatory_ai_prototype.py
```

## Căn cứ pháp lý

- NĐ 15/2018/NĐ-CP — Điều kiện ATTP
- TTLT 13/2016/TTLT-BYT-BGDĐT — Y tế trường học
- QĐ 3958/QĐ-BYT 2025 — Dinh dưỡng học đường
