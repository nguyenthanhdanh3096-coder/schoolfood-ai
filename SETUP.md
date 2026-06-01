# HƯỚNG DẪN CÀI ĐẶT & CHẠY SCHOOLFOOD AI

## Yêu cầu
- Python 3.10+ (đã có Python 3.13)
- Tài khoản Anthropic (lấy API Key tại [console.anthropic.com](https://console.anthropic.com))

---

## Bước 1 — Cài packages

```bash
cd /Users/nguyenthanhdanh/Desktop/ABI/SchoolFood_AI/04_Development
pip install -r requirements.txt
```

Hoặc cài thủ công:
```bash
pip install anthropic streamlit pypdf
```

---

## Bước 2 — Chạy app

```bash
streamlit run backend/regulatory_ai_prototype.py
```

App sẽ mở tự động tại `http://localhost:8501`

---

## Bước 3 — Sử dụng

1. Nhập **Claude API Key** vào ô ở sidebar (lấy tại console.anthropic.com)
2. Chọn **vai trò** (phụ huynh / ban giám sát / giáo viên...)
3. Chọn **cấp trường** và nhập **tỉnh/thành phố**
4. Tab **💬 Hỏi đáp AI** — đặt câu hỏi về pháp luật ATTP
5. Tab **✅ Checklist** — điền kết quả kiểm tra, xuất báo cáo

---

## Cấu trúc file

```
04_Development/
├── requirements.txt          ← packages cần cài
├── SETUP.md                  ← file này
└── backend/
    └── regulatory_ai_prototype.py   ← app chính (Streamlit)

03_Product/
├── AI_Prompts/
│   └── regulatory_qa_v1.md   ← system prompt (AI đọc tự động)
└── Checklists/
    └── Tieu_hoc/
        └── checklist_tieu_hoc_v1.md

07_Legal_Regulations/
├── *.pdf                     ← văn bản pháp luật (AI đọc tự động nếu cài pypdf)
└── ...
```

---

## Tính năng v0.2

| Tính năng | Mô tả |
|-----------|-------|
| 💬 Chat AI | Hỏi đáp pháp luật ATTP theo ngôn ngữ thông thường |
| 📚 PDF ingestion | Tự động đọc văn bản pháp luật từ `07_Legal_Regulations/*.pdf` |
| ⚡ Prompt caching | Cache system prompt → giảm latency và chi phí API |
| ✅ Checklist 20 điểm | Kiểm tra ATTP chuẩn pháp luật, ghi chú từng mục |
| 📄 Xuất báo cáo | Tạo báo cáo .txt có thể tải về và gửi Ban giám hiệu |
| 🔘 Câu hỏi gợi ý | 6 câu hỏi phổ biến nhất, click để hỏi ngay |

---

## Lỗi thường gặp

**`ModuleNotFoundError: No module named 'anthropic'`**
→ Chạy: `pip install anthropic streamlit pypdf`

**`AuthenticationError: Invalid API Key`**
→ Kiểm tra lại API Key tại console.anthropic.com → API Keys

**App không mở trình duyệt tự động**
→ Mở thủ công: `http://localhost:8501`

**PDF không được đọc**
→ Đảm bảo đã `pip install pypdf` và file PDF nằm trong `07_Legal_Regulations/`
