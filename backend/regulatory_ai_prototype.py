#!/usr/bin/env python3
"""SchoolFood AI v2.0 — Phase 2A: Vision AI, Dynamic Checklist, Smart Reports"""

import base64
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Múi giờ Việt Nam UTC+7 — dùng cho mọi tính toán thời gian
VN_TZ = timezone(timedelta(hours=7))

def now_vn() -> datetime:
    """Trả về giờ hiện tại theo múi giờ Việt Nam (UTC+7)."""
    return datetime.now(VN_TZ)

import anthropic
import streamlit as st

# Thư mục gốc của repo deploy (04_Development/)
ROOT        = Path(__file__).parent.parent
# Tìm PDF: ưu tiên thư mục deploy, fallback về thư mục gốc project
LEGAL_DIR   = ROOT / "legal_docs"
if not LEGAL_DIR.exists():
    LEGAL_DIR = ROOT.parent / "07_Legal_Regulations"
# Tìm prompt: ưu tiên thư mục deploy
PROMPT_FILE = ROOT / "prompts/regulatory_qa_v1.md"
if not PROMPT_FILE.exists():
    PROMPT_FILE = ROOT.parent / "03_Product/AI_Prompts/regulatory_qa_v1.md"
MODEL, MAX_TOK = "claude-sonnet-4-6", 1500

# ── Định nghĩa mục bắt buộc & ngưỡng điểm ────────────────────────────────────
CRITICAL_ITEMS = {"C03", "C07", "C09", "C10", "C11", "C18", "C20"}
# C03: hạn dùng, C07: nhiệt độ nhận, C09: nhiệt độ chia, C10: thời gian nấu
# C11: màu/mùi, C18: sổ kiểm thực, C20: mẫu lưu
SCORE_EXCELLENT  = 18   # ≥ 18/20 → Đạt chuẩn
SCORE_ACCEPTABLE = 15   # 15–17/20 → Cần cải thiện
# < 15 → Không đạt

# ── Tiêu chuẩn dinh dưỡng theo cấp học (QĐ 3958/QĐ-BYT 2025) ────────────────
NUTRITION = {
    "Tiểu Học (6–11 tuổi)": {
        "short": "Tiểu Học",
        "kcal": "500–650 kcal",
        "pct_day": "30–40%",
        "protein_pct": "13–20%",
        "fat_pct": "25–30%",
        "carb_pct": "55–65%",
        "meat_g": 50,
        "veg_g": 80,
        "veg_range": "80–120g",
        "note": "Bữa phụ buổi chiều thêm sữa hoặc sản phẩm sữa (5–10% nhu cầu ngày)",
    },
    "THCS (12–15 tuổi)": {
        "short": "THCS",
        "kcal": "650–800 kcal",
        "pct_day": "35–42%",
        "protein_pct": "13–20%",
        "fat_pct": "20–30%",
        "carb_pct": "55–65%",
        "meat_g": 70,
        "veg_g": 100,
        "veg_range": "100–150g",
        "note": "Cá/hải sản tối thiểu 2–3 lần/tuần, đậu hũ/đậu 2 lần/tuần",
    },
    "THPT (16–18 tuổi)": {
        "short": "THPT",
        "kcal": "750–900 kcal",
        "pct_day": "38–45%",
        "protein_pct": "13–20%",
        "fat_pct": "20–30%",
        "carb_pct": "55–65%",
        "meat_g": 80,
        "veg_g": 120,
        "veg_range": "100–150g",
        "note": "Nam và nữ có nhu cầu năng lượng khác nhau — thực đơn nên đa dạng",
    },
}

# ── Hệ thống cảnh báo theo cấp độ ────────────────────────────────────────────
ALERT_SYSTEM = {
    "CRITICAL": {
        "icon": "🔴", "label": "CRITICAL — Nguy hiểm tức thì",
        "color": "#DC2626", "bg": "#FEF2F2", "border": "#FCA5A5",
        "triggers": [
            "Bất kỳ mục bắt buộc (*) nào bị KHÔNG ĐẠT",
            "Phát hiện dấu hiệu ngộ độc tập thể (≥ 2 học sinh có triệu chứng)",
            "Thức ăn hỏng rõ ràng: mốc, mùi chua, màu lạ bất thường",
        ],
        "notify": [
            "🏫 Hiệu Trưởng — GỌI ĐIỆN NGAY",
            "🏥 Y Tế Học Đường — NGAY LẬP TỨC",
            "👥 Ban Giám Sát — TRONG 5 PHÚT",
            "📞 Cấp cứu 115 — Nếu có học sinh bị ảnh hưởng",
            "🏛️ Sở Y Tế địa phương — TRONG 24 GIỜ (bắt buộc theo luật)",
        ],
        "timeframe": "Trong 5 phút",
        "action": "⛔ Tạm dừng bữa ăn ngay · Giữ nguyên mẫu thức ăn (không vứt, không rửa) · Cách ly học sinh bị ảnh hưởng",
    },
    "MAJOR": {
        "icon": "🟠", "label": "MAJOR — Xử lý trong ngày",
        "color": "#D97706", "bg": "#FFFBEB", "border": "#FCD34D",
        "triggers": [
            "Tổng điểm dưới 15/20 (dù không có critical item nào fail)",
            "Từ 3 mục KHÔNG ĐẠT trong cùng một nhóm",
            "Nhà Cung Cấp thiếu hóa đơn hoặc giấy tờ ATTP",
        ],
        "notify": [
            "🏫 Hiệu Trưởng — Trong 2 giờ",
            "🏥 Y Tế Học Đường — Ngay",
            "🏢 Nhà Cung Cấp — Yêu cầu giải trình và khắc phục",
        ],
        "timeframe": "Trong 2–4 giờ",
        "action": "⚠️ Yêu cầu Nhà Cung Cấp khắc phục trước bữa ăn tiếp theo · Kiểm tra lại trong 24h · Ghi vào hồ sơ theo dõi",
    },
    "MINOR": {
        "icon": "🟡", "label": "MINOR — Cải thiện trong tuần",
        "color": "#CA8A04", "bg": "#FEFCE8", "border": "#FDE68A",
        "triggers": [
            "Tổng điểm đạt 15–17/20 (dưới mức xuất sắc)",
            "Có 1–2 mục không bắt buộc bị KHÔNG ĐẠT",
        ],
        "notify": [
            "🏥 Y Tế Học Đường — Lưu hồ sơ theo dõi",
            "🏢 Nhà Cung Cấp — Thông báo cải thiện",
        ],
        "timeframe": "Trong 24–48 giờ",
        "action": "📝 Ghi vào hồ sơ · Yêu cầu cải thiện trong lần kiểm tra tiếp theo",
    },
    "OK": {
        "icon": "✅", "label": "ĐẠT CHUẨN — Lưu hồ sơ",
        "color": "#16A34A", "bg": "#F0FDF4", "border": "#86EFAC",
        "triggers": [
            "Tất cả mục bắt buộc (*) đều ĐẠT",
            "Tổng điểm từ 18/20 trở lên",
        ],
        "notify": [
            "🏫 Hiệu Trưởng — Báo cáo tổng hợp cuối tháng",
            "👨‍👩‍👧 Phụ Huynh — Chia sẻ kết quả tốt qua ứng dụng (tuỳ chọn)",
        ],
        "timeframe": "Cuối tháng",
        "action": "✅ Lưu báo cáo vào hồ sơ · Duy trì tiêu chuẩn",
    },
}

# ── Lịch kiểm tra & tần suất ─────────────────────────────────────────────────
SCHEDULE = [
    {
        "role": "🏥 Y Tế Học Đường",
        "freq": "Mỗi ngày có bữa ăn",
        "when": "10:00–10:45 (trước bữa trưa 30–45 phút)",
        "what": "Kiểm thực 3 bước (theo sổ bắt buộc)",
        "notice": "Không cần báo trước nhà cung cấp",
        "report": "Lưu sổ tại bếp · Báo Hiệu Trưởng ngay khi có vấn đề",
        "color": "#2563EB",
    },
    {
        "role": "👥 Ban Giám Sát (PHHS)",
        "freq": "2 lần / tuần tối thiểu",
        "when": "Thứ 2–3 (báo trước 1 ngày) + 1 lần đột xuất bất kỳ",
        "what": "Checklist 20 điểm đầy đủ + ảnh minh chứng",
        "notice": "1 lần báo trước ≥ 24h, 1 lần KHÔNG báo trước (đột xuất)",
        "report": "Gửi báo cáo cho Hiệu Trưởng trong 24h sau kiểm tra",
        "color": "#7C3AED",
    },
    {
        "role": "🏫 Ban Giám Hiệu",
        "freq": "1 lần / tháng",
        "when": "Tuần cuối mỗi tháng — xem tổng hợp + spot-check",
        "what": "Duyệt báo cáo tháng + kiểm tra xác suất 5 mục ngẫu nhiên",
        "notice": "Không cần báo trước",
        "report": "Tổng hợp báo cáo học kỳ gửi Sở GD&ĐT",
        "color": "#0D9488",
    },
    {
        "role": "🏛️ Sở GD&ĐT / Sở Y Tế",
        "freq": "1–2 lần / học kỳ",
        "when": "Không cố định — kiểm tra đột xuất hoàn toàn",
        "what": "Kiểm tra toàn diện + lấy mẫu xét nghiệm tại chỗ",
        "notice": "Không báo trước — trường cần luôn sẵn sàng",
        "report": "Kết quả gửi Bộ GD&ĐT và Bộ Y Tế",
        "color": "#B45309",
    },
]

# ── CSS ────────────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    #MainMenu, footer, header { visibility: hidden; }
    .stApp { background-color: #F5F7FA; }

    .sf-header {
        background: linear-gradient(135deg, #1B3B6F 0%, #2563EB 100%);
        padding: 20px 28px; border-radius: 14px; margin-bottom: 20px;
    }
    .sf-header h1 { color: white; font-size: 1.7rem; font-weight: 700; margin: 0; }
    .sf-header p  { color: #BFDBFE; font-size: 0.9rem; margin: 5px 0 0 0; }

    .sf-card {
        background: white; border-radius: 12px; padding: 18px 22px;
        margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.07);
        border: 1px solid #E8ECF0;
    }
    .sf-card-title { font-size: 1rem; font-weight: 600; color: #1E293B; margin-bottom: 5px; }
    .sf-card-body  { font-size: 0.875rem; color: #475569; line-height: 1.65; }

    /* Checklist item row */
    .cl-row {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 10px 0; border-bottom: 1px solid #F1F5F9;
    }
    .cl-code {
        font-size: 0.72rem; font-weight: 700; color: #94A3B8;
        min-width: 32px; padding-top: 3px; letter-spacing: 0.03em;
    }
    .cl-desc {
        font-size: 0.9rem; font-weight: 500; color: #1E293B; flex: 1; line-height: 1.5;
    }
    .cl-sub {
        font-size: 0.78rem; color: #64748B; font-weight: 400; margin-top: 2px;
    }
    .badge-critical {
        display: inline-block; background: #FEE2E2; color: #991B1B;
        font-size: 0.68rem; font-weight: 700; padding: 2px 7px;
        border-radius: 10px; margin-left: 6px; vertical-align: middle;
        letter-spacing: 0.04em; border: 1px solid #FECACA;
    }
    .badge-pass {
        background: #DCFCE7; color: #166534;
        padding: 3px 10px; border-radius: 20px;
        font-size: 0.78rem; font-weight: 600; border: 1px solid #BBF7D0;
    }
    .badge-fail {
        background: #FEE2E2; color: #991B1B;
        padding: 3px 10px; border-radius: 20px;
        font-size: 0.78rem; font-weight: 600; border: 1px solid #FECACA;
    }

    /* Group title */
    .group-title {
        font-size: 0.78rem; font-weight: 700; color: #475569;
        text-transform: uppercase; letter-spacing: 0.08em;
        padding: 14px 0 8px 0; border-bottom: 2px solid #E2E8F0;
        margin-bottom: 4px;
    }

    /* Metric */
    .metric-box {
        background: white; border-radius: 10px; padding: 14px 10px;
        text-align: center; border: 1px solid #E8ECF0;
        min-height: 110px;
        display: flex; flex-direction: column;
        justify-content: center; align-items: center; gap: 2px;
    }
    .metric-num  { font-size: 2rem; font-weight: 700; line-height: 1.1; }
    .metric-lbl  { font-size: 0.78rem; color: #64748B; line-height: 1.3; }
    .c-green  { color: #16A34A; } .c-red  { color: #DC2626; }
    .c-blue   { color: #2563EB; } .c-orange{ color: #D97706; }

    /* Alert card */
    .alert-critical { background:#FEF2F2; border:2px solid #FCA5A5; border-radius:12px; padding:16px 20px; }
    .alert-major    { background:#FFFBEB; border:2px solid #FCD34D; border-radius:12px; padding:16px 20px; }
    .alert-minor    { background:#FEFCE8; border:2px solid #FDE68A; border-radius:12px; padding:16px 20px; }
    .alert-ok       { background:#F0FDF4; border:2px solid #86EFAC; border-radius:12px; padding:16px 20px; }
    .alert-title  { font-size: 1rem; font-weight: 700; margin-bottom: 8px; }
    .alert-body   { font-size: 0.85rem; line-height: 1.7; }

    /* Nutrition banner */
    .nutrition-banner {
        background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 10px;
        padding: 12px 16px; margin-bottom: 14px;
    }
    .nutrition-label { font-size: 0.78rem; color: #1D4ED8; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.06em; }
    .nutrition-grid { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 6px; }
    .nutrition-item { font-size: 0.82rem; color: #1E40AF; }
    .nutrition-val  { font-weight: 700; }

    /* Schedule card */
    .schedule-card {
        background: white; border-radius: 10px; padding: 16px 20px;
        margin-bottom: 10px; border: 1px solid #E2E8F0;
        border-left: 4px solid var(--sc-color, #64748B);
    }
    .schedule-role  { font-size: 0.95rem; font-weight: 700; color: #1E293B; margin-bottom: 6px; }
    .schedule-row   { font-size: 0.83rem; color: #475569; margin: 3px 0; }
    .schedule-key   { font-weight: 600; color: #334155; min-width: 100px; display: inline-block; }

    /* Emergency */
    .emergency-header { background:#DC2626; color:white; border-radius:10px;
        padding:14px 18px; margin-bottom:16px; font-weight:700; font-size:1rem; }

    /* Divider */
    .sf-div { border-top: 1px solid #E2E8F0; margin: 16px 0; }

    /* Section header */
    .sec-hdr { font-size:0.72rem; font-weight:700; color:#94A3B8;
        text-transform:uppercase; letter-spacing:0.08em; margin:16px 0 8px; }

    .stButton > button { border-radius: 8px !important; font-family:'Inter',sans-serif !important; font-weight:500 !important; }
    .stTextInput > div > div > input { border-radius: 8px !important; }
    div[data-testid="stChatInput"] textarea { font-family:'Inter',sans-serif !important; }

    /* ── Checklist segmented control animations (CSS-only, no JS needed) ── */
    /* Áp dụng cho cả direct children và div-wrapped children (tuỳ BaseWeb version) */
    [data-baseweb="button-group"] button {
        border-radius: 8px !important;
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        padding: 5px 12px !important;
        transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.2s ease !important;
        letter-spacing: 0.02em !important;
        cursor: pointer !important;
    }
    [data-baseweb="button-group"] button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 3px 8px rgba(0,0,0,0.12) !important;
    }

    /* Nút 1 — "Chưa chấm": viền nháy, text luôn đọc được */
    [data-baseweb="button-group"] > button:nth-child(1):not([aria-pressed="true"]):not([aria-checked="true"]),
    [data-baseweb="button-group"] > div:nth-child(1) > button:not([aria-pressed="true"]):not([aria-checked="true"]) {
        background: #F8FAFC !important;
        color: #374151 !important;          /* Đủ tối để đọc rõ */
        border: 1.5px dashed #CBD5E1 !important;
        animation: pendingBorder 2.5s ease-in-out infinite !important;
    }
    @keyframes pendingBorder {
        0%, 100% { border-color: #CBD5E1; background: #F8FAFC; }
        50%       { border-color: #F59E0B; background: #FFFBEB; }
        /* Viền chuyển từ xám → vàng hổ phách — "cần chú ý" */
    }

    /* Nút 2 — "✅ Đạt": xanh lá + pop animation khi chọn */
    [data-baseweb="button-group"] > button:nth-child(2):not([aria-pressed="true"]):not([aria-checked="true"]),
    [data-baseweb="button-group"] > div:nth-child(2) > button:not([aria-pressed="true"]):not([aria-checked="true"]) {
        background: #F0FDF4 !important; color: #16A34A !important;
        border: 1.5px solid #BBF7D0 !important;
    }
    [data-baseweb="button-group"] > button:nth-child(2)[aria-pressed="true"],
    [data-baseweb="button-group"] > button:nth-child(2)[aria-checked="true"],
    [data-baseweb="button-group"] > div:nth-child(2) > button[aria-pressed="true"],
    [data-baseweb="button-group"] > div:nth-child(2) > button[aria-checked="true"] {
        background: #16A34A !important; color: #FFFFFF !important;
        border: 1.5px solid #16A34A !important;
        box-shadow: 0 0 0 3px rgba(22,163,74,0.25), 0 4px 14px rgba(22,163,74,0.35) !important;
        animation: passClick 0.38s cubic-bezier(0.34, 1.56, 0.64, 1) forwards !important;
    }
    @keyframes passClick {
        0%   { transform: scale(0.88); }
        55%  { transform: scale(1.10); }
        100% { transform: scale(1.00); }
    }

    /* Nút 3 — "❌ Không Đạt": đỏ + shake animation khi chọn */
    [data-baseweb="button-group"] > button:nth-child(3):not([aria-pressed="true"]):not([aria-checked="true"]),
    [data-baseweb="button-group"] > div:nth-child(3) > button:not([aria-pressed="true"]):not([aria-checked="true"]) {
        background: #FFF1F2 !important; color: #DC2626 !important;
        border: 1.5px solid #FECACA !important;
    }
    [data-baseweb="button-group"] > button:nth-child(3)[aria-pressed="true"],
    [data-baseweb="button-group"] > button:nth-child(3)[aria-checked="true"],
    [data-baseweb="button-group"] > div:nth-child(3) > button[aria-pressed="true"],
    [data-baseweb="button-group"] > div:nth-child(3) > button[aria-checked="true"] {
        background: #DC2626 !important; color: #FFFFFF !important;
        border: 1.5px solid #DC2626 !important;
        box-shadow: 0 0 0 3px rgba(220,38,38,0.25), 0 4px 14px rgba(220,38,38,0.35) !important;
        animation: failShake 0.48s ease-out forwards !important;
    }
    @keyframes failShake {
        0%,100% { transform: translateX(0) scale(1);    }
        18%     { transform: translateX(-5px) scale(0.97); }
        36%     { transform: translateX(5px)  scale(0.97); }
        54%     { transform: translateX(-4px); }
        72%     { transform: translateX(4px);  }
        90%     { transform: translateX(-2px); }
    }

    /* Reminder banner */
    .reminder-banner {
        background: linear-gradient(135deg,#FEF9C3,#FFFBEB);
        border: 2px solid #F59E0B; border-radius: 12px;
        padding: 14px 20px; margin-bottom: 16px;
    }
    .reminder-title { font-weight: 700; color: #92400E; font-size: 0.95rem; }
    .reminder-body  { font-size: 0.83rem; color: #78350F; margin-top: 5px; line-height: 1.6; }
    .reminder-countdown {
        display: inline-block; background: #F59E0B; color: white;
        border-radius: 20px; padding: 2px 12px; font-weight: 700;
        font-size: 0.8rem; margin-left: 8px;
    }

    /* Validation error box */
    .validation-box {
        background: #FFF7ED; border: 2px solid #FB923C;
        border-radius: 10px; padding: 14px 18px; margin-bottom: 12px;
    }
    .validation-title { font-weight: 700; color: #9A3412; font-size: 0.9rem; margin-bottom: 8px; }
    .validation-item  { font-size: 0.83rem; color: #7C2D12; margin: 4px 0; }

    /* Progress bar completion */
    .completion-bar-wrap {
        background: #E2E8F0; border-radius: 20px; height: 8px; margin: 8px 0;
        overflow: hidden;
    }
    .completion-bar-fill {
        height: 100%; border-radius: 20px;
        transition: width 0.4s ease;
    }
    </style>
    """, unsafe_allow_html=True)


# ── Checklist theo cấp học ────────────────────────────────────────────────────
def get_checklist(level_key: str) -> list:
    n = NUTRITION.get(level_key, NUTRITION["Tiểu Học (6–11 tuổi)"])
    mg, vg, lvl = n["meat_g"], n["veg_g"], n["short"]
    fail_m, fail_v = int(mg * 0.7), int(vg * 0.7)
    return [
        ("📦 Nguồn gốc nguyên liệu", [
            ("C01", False, "Thịt/cá có tem kiểm dịch thú y còn hiệu lực",
             "Xem nhãn mác trên bao bì từng lô hàng",
             "Có tem còn hiệu lực", "Không có tem, hoặc tem đã hết hạn"),
            ("C02", False, "Rau củ có hóa đơn nguồn gốc từ vựa có đăng ký",
             "Yêu cầu xem hóa đơn mua hàng trong ngày",
             "Có hóa đơn hợp lệ đúng ngày", "Mua chợ không rõ nguồn gốc, không hóa đơn"),
            ("C03", True,  "Nguyên liệu đóng gói còn hạn sử dụng ≥ 3 ngày",
             "Kiểm tra date trên bao bì từng loại nguyên liệu",
             "Còn ≥ 3 ngày so với hôm nay", "Hết hạn, hoặc không có ngày sản xuất/hạn dùng"),
            ("C04", False, "Có hóa đơn mua hàng của ngày hôm nay đầy đủ",
             "Yêu cầu xem toàn bộ hóa đơn mua hàng trong ngày",
             "Có hóa đơn hợp lệ, đúng ngày, đủ loại", "Thiếu hóa đơn hoặc không xuất trình được"),
        ]),
        ("🌡️ Bảo quản & vận chuyển", [
            ("C05", False, "Nhiệt độ tủ lạnh thực phẩm sống dưới 5°C",
             "Đọc đồng hồ hoặc đo nhiệt kế tủ trực tiếp",
             "Dưới 5°C", "Từ 5°C trở lên — vùng nguy hiểm, vi khuẩn tăng gấp đôi mỗi 20 phút"),
            ("C06", False, "Thực phẩm sống và chín để riêng, có nhãn phân biệt rõ ràng",
             "Quan sát kho lạnh và tủ lạnh, kiểm tra nhãn",
             "Có ngăn riêng biệt, nhãn ghi rõ loại thực phẩm", "Để chung hoặc không có nhãn phân biệt"),
            ("C07", True,  "Nhiệt độ thức ăn khi nhận tại trường đạt từ 60°C trở lên",
             "Đo nhiệt kế thực phẩm trực tiếp vào từng nồi/khay khi nhận",
             "Từ 60°C trở lên — an toàn", "Dưới 60°C — đã nguội, nguy cơ nhiễm khuẩn cao"),
            ("C08", False, "Thùng/nồi vận chuyển kín nắp, sạch, không có mùi lạ",
             "Quan sát trực tiếp từng thùng chứa khi bàn giao",
             "Kín nắp, bề mặt sạch, không mùi lạ", "Hở nắp, bẩn, hoặc có mùi khó chịu"),
        ]),
        ("🍽️ Thức ăn khi phục vụ", [
            ("C09", True,  "Nhiệt độ thức ăn khi chia đúng chuẩn an toàn",
             "Đo nhiệt kế thực phẩm trực tiếp tại thời điểm bắt đầu chia",
             "Nóng ≥ 60°C · Lạnh ≤ 5°C", "5°C < T < 60°C — VÙNG NGUY HIỂM tuyệt đối"),
            ("C10", True,  "Thời gian từ khi nấu xong đến khi phục vụ dưới 2 giờ",
             "Hỏi bếp trưởng và đối chiếu nhật ký giờ nấu",
             "Dưới 2 giờ — an toàn hoàn toàn", "Trên 4 giờ ở nhiệt độ phòng — nguy hiểm"),
            ("C11", True,  "Màu sắc và mùi vị thức ăn bình thường, không có dấu hiệu hỏng",
             "Quan sát màu, ngửi mùi trực tiếp từng món; hỏi ý kiến bếp trưởng",
             "Màu tự nhiên đặc trưng, mùi thơm ngon đúng món", "Màu lạ, mùi chua/hôi, có nấm mốc/nhớt"),
            ("C12", False, f"Khẩu phần thịt/cá đạt tiêu chuẩn cấp {lvl}: từ {mg}g/học sinh",
             f"Cân hoặc ước lượng suất ăn thực tế, so với định mức {mg}g đã đăng ký",
             f"Từ {mg}g/học sinh trở lên (cấp {lvl})", f"Dưới {fail_m}g — thiếu hụt dưới 70% định mức"),
            ("C13", False, f"Rau xanh đủ khẩu phần cấp {lvl}: từ {vg}g/học sinh",
             f"Ước lượng lượng rau trong suất ăn thực tế, tiêu chuẩn {n['veg_range']}",
             f"Từ {vg}g/học sinh (cấp {lvl})", f"Dưới {fail_v}g — thiếu rau nghiêm trọng"),
        ]),
        ("🧼 Vệ sinh dụng cụ & nhân viên", [
            ("C14", False, "Bát đũa muỗng sạch, khô ráo, không còn vết thức ăn cũ",
             "Kiểm tra ngẫu nhiên 5–10 bộ dụng cụ",
             "Sạch, khô, không mùi", "Còn thức ăn cũ, ẩm ướt, hoặc có mùi hôi"),
            ("C15", False, "Nhân viên đeo khẩu trang và găng tay đúng cách khi chia cơm",
             "Quan sát trực tiếp toàn bộ nhân viên tham gia chia",
             "Tất cả đều đeo đầy đủ và đúng cách", "Có người không đeo hoặc đeo sai, dùng lại găng cũ"),
            ("C16", False, "Nhân viên không ho/hắt hơi trực tiếp vào thức ăn",
             "Quan sát liên tục trong suốt 15 phút chia cơm",
             "Quay mặt đi hoặc che kín miệng khi cần", "Ho/hắt hơi thẳng vào thức ăn — không che chắn"),
            ("C17", False, "Khu vực chia cơm gọn sạch, không có côn trùng",
             "Quan sát mặt bàn, sàn, cửa sổ và các góc xung quanh khu vực chia",
             "Sạch sẽ, không có ruồi/gián/kiến", "Bẩn, hoặc có côn trùng xuất hiện"),
        ]),
        ("📋 Hồ sơ & giấy tờ", [
            ("C18", True,  "Sổ kiểm thực 3 bước điền đầy đủ hôm nay, có chữ ký xác nhận",
             "Yêu cầu xem sổ tại bếp — đây là tài liệu bắt buộc theo pháp luật",
             "Ghi đủ 3 bước (trước/trong/sau chế biến), có chữ ký Y Tế", "Chưa điền, thiếu bước, hoặc không có chữ ký"),
            ("C19", False, "Thực đơn thực tế phục vụ khớp với thực đơn đã đăng ký trước",
             "So sánh menu treo tại bếp với các món đang thực tế phục vụ",
             "Khớp hoàn toàn với đăng ký", "Thay đổi món mà không thông báo trước"),
            ("C20", True,  "Có mẫu lưu thức ăn 24h từng món, đủ nhãn ngày giờ",
             "Yêu cầu xem tủ lạnh lưu mẫu — mỗi món cần ≥ 100g, nhãn đầy đủ",
             "Có mẫu từng món, nhãn ghi: tên món + giờ lấy mẫu + ngày", "Không có mẫu lưu, thiếu nhãn, hoặc mẫu không đủ lượng"),
        ]),
    ]

TOTAL_ITEMS = 20


# ── Helpers ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_legal_pdfs() -> str:
    try:
        import pypdf
    except ImportError:
        return ""
    parts = []
    for p in sorted(LEGAL_DIR.glob("*.pdf")):
        try:
            r = pypdf.PdfReader(str(p))
            txt = "\n".join(pg.extract_text() or "" for pg in r.pages).strip()
            if txt:
                parts.append(f"=== {p.name} ===\n{txt}")
        except Exception:
            pass
    return "\n\n".join(parts)


@st.cache_data(ttl=3600, show_spinner=False)
def build_system_prompt(role: str, level: str, loc: str) -> str:
    if PROMPT_FILE.exists():
        raw = PROMPT_FILE.read_text(encoding="utf-8")
        s = raw.find("```\n") + 4; e = raw.find("\n```", s)
        base = raw[s:e] if e != -1 and s > 3 else raw
    else:
        base = "Bạn là chuyên gia ATVSTP trường học tại Việt Nam. Trả lời đơn giản, trích dẫn pháp luật."
    base = base.replace("{user_role}", role).replace("{school_level}", level).replace("{location}", loc)
    pdfs = load_legal_pdfs()
    if pdfs:
        base += "\n\n=== VĂN BẢN PHÁP LUẬT ĐÍNH KÈM ===\nƯu tiên trích dẫn từ các văn bản sau:\n\n" + pdfs
    return base


def ask_claude(client, system: str, history: list, user_input: str) -> str:
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=MAX_TOK,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=history + [{"role": "user", "content": user_input}],
        )
        return r.content[0].text
    except anthropic.AuthenticationError:
        return "❌ API Key không hợp lệ. Kiểm tra lại ở sidebar."
    except anthropic.RateLimitError:
        return "⚠️ Vượt giới hạn API. Thử lại sau vài giây."
    except Exception as e:
        return f"❌ Lỗi: {e}"


def determine_alert(results: dict, cl: list) -> str:
    """Xác định mức cảnh báo dựa trên kết quả checklist."""
    pass_set  = {c for c, v in results.items() if v == "✅ Đạt"}
    fail_set  = {c for c, v in results.items() if v == "❌ Không Đạt"}
    critical_fails = CRITICAL_ITEMS & fail_set
    pass_count = len(pass_set)

    if critical_fails:
        return "CRITICAL"
    if pass_count < SCORE_ACCEPTABLE:
        return "MAJOR"
    # Kiểm tra ≥3 FAIL cùng nhóm
    for _, items in cl:
        codes = {code for code, *_ in items}
        if len(codes & fail_set) >= 3:
            return "MAJOR"
    if pass_count < SCORE_EXCELLENT:
        return "MINOR"
    return "OK"


# ── Hệ thống nhắc nhở kiểm tra theo vai trò ───────────────────────────────────
_REMINDER_TIMES = {
    "Y Tế Học Đường": {
        "hour": 10, "min": 0,
        "days": [0, 1, 2, 3, 4],          # Thứ 2–6
        "task": "Kiểm thực 3 bước bữa trưa (trước 10:45)",
        "tab":  "✅ Checklist kiểm tra",
    },
    "Ban Giám Sát": {
        "hour": 10, "min": 0,
        "days": [0, 2],                    # Thứ 2, Thứ 4 (định kỳ có báo trước)
        "task": "Checklist 20 điểm định kỳ (Thứ 2 & Thứ 4)",
        "tab":  "✅ Checklist kiểm tra",
    },
    "Ban Giám Hiệu": {
        "hour": 9, "min": 0,
        "days": [0, 1, 2, 3, 4],
        "task": "Xem tổng hợp báo cáo tuần & duyệt checklist",
        "tab":  "📅 Lịch & thông báo",
        "last_week_only": True,
    },
}


def get_inspection_reminder(role: str) -> dict | None:
    """Trả về thông tin nhắc nhở nếu còn ≤ 15 phút đến giờ kiểm tra."""
    import calendar
    now = now_vn()
    if now.weekday() >= 5:          # Thứ 7, Chủ nhật — không có bữa bán trú
        return None

    info = _REMINDER_TIMES.get(role)
    if not info or now.weekday() not in info["days"]:
        return None

    if info.get("last_week_only"):
        last_day = calendar.monthrange(now.year, now.month)[1]
        if now.day < last_day - 6:  # Không phải tuần cuối tháng
            return None

    inspect_mins  = info["hour"] * 60 + info["min"]
    current_mins  = now.hour * 60 + now.minute
    mins_left     = inspect_mins - current_mins

    if 0 <= mins_left <= 15:
        return {
            "task":      info["task"],
            "time":      f"{info['hour']:02d}:{info['min']:02d}",
            "mins_left": mins_left,
            "tab":       info["tab"],
        }
    return None


def show_reminder_banner(role: str):
    """Hiển thị banner nhắc nhở và toast nếu trong vòng 15 phút trước giờ kiểm tra."""
    r = get_inspection_reminder(role)
    if not r:
        return
    key = f"reminded_{role}_{now_vn().strftime('%Y%m%d%H%M')[:12]}"
    if not st.session_state.get(key):
        st.toast(f"⏰ Còn {r['mins_left']} phút đến giờ kiểm tra!", icon="🔔")
        st.session_state[key] = True
    st.markdown(f"""
    <div class="reminder-banner">
        <div class="reminder-title">
            ⏰ NHẮC KIỂM TRA <span class="reminder-countdown">Còn {r['mins_left']} phút</span>
        </div>
        <div class="reminder-body">
            <b>Nhiệm vụ:</b> {r['task']}<br>
            <b>Giờ thực hiện:</b> {r['time']} · <b>Chuyển đến tab:</b> {r['tab']}
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Validation checklist trước khi xuất báo cáo ────────────────────────────────
def validate_checklist(results: dict, photos: dict) -> list[str]:
    """Trả về danh sách lỗi. Rỗng = hợp lệ, được phép xuất báo cáo."""
    errors = []

    unanswered = sorted(c for c, v in results.items() if v == "Chưa chấm")
    if unanswered:
        errors.append(
            f"Còn {len(unanswered)} mục chưa được đánh giá: "
            + ", ".join(unanswered)
        )

    has_fail = any(v == "❌ Không Đạt" for v in results.values())
    total_photos = sum(
        (len(v) if isinstance(v, list) else 1)
        for v in photos.values() if v
    )
    if has_fail and total_photos == 0:
        errors.append(
            "Có mục KHÔNG ĐẠT — bắt buộc cung cấp ít nhất 1 ảnh minh chứng "
            "(mở phần '📷 Ảnh minh chứng' bên dưới mỗi nhóm để chụp/tải ảnh)"
        )

    return errors


# ── Cơ sở pháp lý dùng cho tất cả AI analysis ───────────────────────────────
_LEGAL_BASIS = """
CĂN CỨ PHÁP LÝ VÀ TIÊU CHUẨN KỸ THUẬT ÁP DỤNG:
1. NĐ 15/2018/NĐ-CP — Quy định điều kiện đảm bảo ATTP, yêu cầu bếp ăn tập thể
2. TTLT 13/2016/TTLT-BYT-BGDĐT — Công tác y tế trường học, kiểm soát bữa ăn học đường
3. QĐ 3958/QĐ-BYT ngày 25/12/2025 — Hướng dẫn dinh dưỡng bữa ăn học đường
4. QCVN 8-1:2011/BYT — Giới hạn ô nhiễm vi sinh vật (E.coli, Salmonella, Staphylococcus)
5. QCVN 8-2:2011/BYT — Giới hạn ô nhiễm kim loại nặng (chì, cadimi, thuỷ ngân)
6. QCVN 8-3:2012/BYT — Giới hạn dư lượng thuốc bảo vệ thực vật trong thực phẩm
7. Luật ATTP số 55/2010/QH12 — Khung pháp lý tổng thể về an toàn thực phẩm
8. WHO Five Keys to Safer Food — 5 nguyên tắc vệ sinh thực phẩm của WHO
9. Codex Alimentarius CAC/RCP 1-1969 — Quy phạm thực hành vệ sinh tổng quát
10. Nguyên tắc HACCP (Hazard Analysis Critical Control Points) — Phân tích mối nguy
VÙNG NHIỆT ĐỘ NGUY HIỂM: 5°C – 60°C (vi khuẩn tăng gấp đôi mỗi 20 phút)
"""

_VISUAL_CRITERIA = """
TIÊU CHÍ ĐÁNH GIÁ TRỰC QUAN (Căn cứ WHO Food Safety Visual Inspection Guide + QCVN):
- Màu sắc thực phẩm: bất thường (xanh, đen, xám) → nguy cơ nhiễm khuẩn/mốc
- Bề mặt: nhớt, ẩm ướt bất thường → dấu hiệu vi khuẩn phát triển
- Mùi: chua, hôi, khác lạ → phân huỷ protein hoặc nhiễm khuẩn
- Nấm mốc: đốm trắng/xanh/đen → Aspergillus, Penicillium, Fusarium
- Côn trùng: ruồi, gián, kiến → vector lây truyền Salmonella, E.coli
- Nhiệt độ: <60°C (nóng) hoặc >5°C (lạnh) → vùng nguy hiểm theo HACCP
- Sổ kiểm thực: thiếu chữ ký, thiếu bước → vi phạm TTLT 13/2016 Điều 9
- Dụng cụ: rỉ sét, nứt vỡ → nơi trú ẩn vi khuẩn, không đảm bảo NĐ 15/2018
"""


# ── AI #2: Phân tích ảnh rủi ro ATTP (Claude Vision) ─────────────────────────
def analyze_photo_ai(photo_bytes: bytes, group_name: str, api_key: str) -> dict:
    """Gọi Claude Vision phân tích ảnh ATTP dựa trên chuẩn WHO + QCVN + NĐ 15/2018."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        b64 = base64.standard_b64encode(photo_bytes).decode()
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=700,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": f"""Bạn là chuyên gia kiểm tra ATTP trường học Việt Nam.
Nhóm kiểm tra: {group_name}

{_VISUAL_CRITERIA}

Phân tích ảnh theo các tiêu chí trên. Trả lời JSON (không thêm text ngoài JSON):
{{
  "risk_level": "OK" hoặc "WARNING" hoặc "CRITICAL",
  "issues": ["vấn đề cụ thể + căn cứ pháp lý/kỹ thuật nếu có"],
  "positives": ["điểm đạt chuẩn quan sát được"],
  "recommendation": "hành động khắc phục cụ thể + thời hạn (để trống nếu OK)",
  "legal_ref": "văn bản pháp lý áp dụng chính (ví dụ: QCVN 8-1:2011/BYT)",
  "confidence": 0.85
}}"""}
                ]
            }]
        )
        text = resp.content[0].text.strip()
        s, e = text.find("{"), text.rfind("}") + 1
        return json.loads(text[s:e]) if s != -1 and e > s else \
               {"risk_level": "OK", "issues": [], "positives": [],
                "recommendation": "", "legal_ref": "", "confidence": 0.5}
    except Exception as ex:
        return {"risk_level": "ERROR", "issues": [str(ex)], "positives": [],
                "recommendation": "", "legal_ref": "", "confidence": 0}


# ── AI #1: Checklist động theo thực đơn ──────────────────────────────────────
def generate_extra_checklist(menu: str, school_level: str, api_key: str) -> list:
    """Tạo 3-5 điểm kiểm tra bổ sung đặc thù theo thực đơn, có căn cứ QCVN/NĐ 15."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": f"""Bạn là chuyên gia ATTP trường học Việt Nam.
Thực đơn hôm nay ({school_level}): {menu}

{_LEGAL_BASIS}

Dựa trên từng nguyên liệu trong thực đơn, tạo 3-5 điểm kiểm tra ATTP BỔ SUNG
(ngoài 20 điểm chuẩn), đặc thù cho nguyên liệu đó, có dẫn chiếu quy chuẩn.

Trả lời JSON array (không thêm text khác):
[
  {{
    "code": "E01",
    "ingredient": "Tên nguyên liệu cụ thể",
    "desc": "Mô tả điểm kiểm tra (ngắn gọn, dưới 15 từ)",
    "how": "Cách kiểm tra thực tế (dụng cụ cần thiết nếu có)",
    "pass": "Tiêu chí đạt (kèm giá trị cụ thể nếu có: nhiệt độ, màu sắc...)",
    "fail": "Tiêu chí không đạt (dấu hiệu cụ thể cần nhận biết)",
    "is_critical": false,
    "legal_ref": "Căn cứ: QCVN... / NĐ 15/2018 Điều... / WHO...",
    "why": "Giải thích ngắn tại sao nguyên liệu này cần kiểm tra điểm này"
  }}
]"""}]
        )
        text = resp.content[0].text.strip()
        s, e = text.find("["), text.rfind("]") + 1
        items = json.loads(text[s:e]) if s != -1 and e > s else []
        for i, item in enumerate(items):
            item["code"] = f"E{i+1:02d}"
        return items
    except Exception:
        return []


# ── AI #3: Báo cáo ngôn ngữ tự nhiên ────────────────────────────────────────
def generate_ai_narrative(results: dict, notes: dict, alert_level: str,
                           school: str, date_str: str, menu: str,
                           pass_count: int, total: int,
                           level_key: str, api_key: str) -> str:
    """Claude viết tóm tắt báo cáo kiểm tra bằng tiếng Việt tự nhiên."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        fail_list = [f"{c} ({notes.get(c,'').strip() or 'không có ghi chú'})"
                     for c, v in results.items() if v == "❌ Không Đạt"]
        context = (
            f"Trường: {school or '(chưa nhập)'} | Cấp: {level_key} | Ngày: {date_str}\n"
            f"Thực đơn: {menu or '(chưa nhập)'}\n"
            f"Kết quả: {pass_count}/{total} đạt chuẩn | Cảnh báo: {alert_level}\n"
            f"Mục không đạt: {', '.join(fail_list) if fail_list else 'Không có'}"
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": f"""Viết đoạn tóm tắt báo cáo ATTP (120–160 từ) bằng tiếng Việt:
{context}

Yêu cầu:
- Văn phong chuyên nghiệp, dễ hiểu với phụ huynh và ban giám hiệu
- Nêu điểm tốt trước, điểm cần cải thiện sau
- Có khuyến nghị cụ thể nếu có mục không đạt
- Kết thúc bằng đánh giá tổng thể 1 câu
- Không dùng markdown header hay bullet points, viết thành đoạn văn"""
            }]
        )
        return resp.content[0].text.strip()
    except Exception as ex:
        return f"(Không tạo được tóm tắt AI: {ex})"


# ── Tạo báo cáo Word chuẩn chính phủ (.docx) ────────────────────────────────
def _docx_set_font(run, bold=False, size_pt=12, color=None):
    """Helper: thiết lập font Times New Roman cho run."""
    from docx.shared import Pt, RGBColor
    run.font.name     = "Times New Roman"
    run.font.size     = Pt(size_pt)
    run.font.bold     = bold
    if color:
        run.font.color.rgb = RGBColor(*color)


def _docx_para(doc, text, bold=False, size=12, align="left", space_before=0, space_after=6):
    """Thêm paragraph với Times New Roman, trả về paragraph."""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    _MAP = {"left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}
    p.alignment = _MAP.get(align, WD_ALIGN_PARAGRAPH.LEFT)
    run = p.add_run(text)
    _docx_set_font(run, bold=bold, size_pt=size)
    return p


def _docx_table_header(table, headers: list, bg_color="1B3B6F"):
    """Tô màu header row của table."""
    from docx.oxml.ns import qn
    from docx.oxml   import OxmlElement
    from docx.shared  import Pt, RGBColor
    row = table.rows[0]
    for i, (cell, hdr) in enumerate(zip(row.cells, headers)):
        cell.text = ""
        run = cell.paragraphs[0].add_run(hdr)
        _docx_set_font(run, bold=True, size_pt=11, color=(255, 255, 255))
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement("w:shd")
        shd.set(qn("w:val"),   "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"),  bg_color)
        tcPr.append(shd)


def generate_word_report(school: str, date_str: str, insp: str, menu: str,
                          level_key: str, results: dict, notes: dict,
                          pass_count: int, fail_count: int, alert_key: str,
                          cl: list, ai_narrative: str,
                          photo_analysis: dict) -> bytes:
    """
    Tạo báo cáo kiểm tra ATTP định dạng Word (.docx) chuẩn văn bản hành chính Việt Nam.
    Font Times New Roman, trình bày như báo cáo gửi cấp Bộ/Chính phủ.
    """
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns  import qn
    from docx.oxml     import OxmlElement
    from io import BytesIO

    doc = Document()

    # ── Lề trang (chuẩn văn bản hành chính Việt Nam) ─────────────────────────
    sec = doc.sections[0]
    sec.top_margin    = Cm(2.0)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin   = Cm(3.0)   # lề trái rộng cho đóng bìa
    sec.right_margin  = Cm(2.0)

    # ── Quốc hiệu & Tiêu ngữ ─────────────────────────────────────────────────
    _docx_para(doc, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
               bold=True, size=13, align="center", space_after=2)
    _docx_para(doc, "Độc lập – Tự do – Hạnh phúc",
               bold=True, size=12, align="center", space_after=2)
    # Đường kẻ ngang
    p_line = doc.add_paragraph()
    p_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p_line.add_run("───────────────────────")
    _docx_set_font(r, size_pt=11)
    p_line.paragraph_format.space_after = Pt(4)

    # Số hiệu và ngày
    vn_days = ["Thứ Hai","Thứ Ba","Thứ Tư","Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ Nhật"]
    try:
        dt_obj   = datetime.strptime(date_str, "%d/%m/%Y")
        day_name = vn_days[dt_obj.weekday()]
        date_full = f"TP. Hồ Chí Minh, {day_name} ngày {dt_obj.day} tháng {dt_obj.month} năm {dt_obj.year}"
    except Exception:
        date_full = f"TP. Hồ Chí Minh, ngày ... tháng ... năm 2026"
    _docx_para(doc, date_full, size=12, align="right", space_before=4, space_after=12)

    # ── Tiêu đề báo cáo ──────────────────────────────────────────────────────
    _docx_para(doc, "BÁO CÁO", bold=True, size=14, align="center", space_before=6, space_after=2)
    _docx_para(doc, "KIỂM TRA AN TOÀN THỰC PHẨM BỮA ĂN HỌC ĐƯỜNG",
               bold=True, size=14, align="center", space_after=12)

    a = ALERT_SYSTEM.get(alert_key, {})
    _docx_para(doc,
               f"Kính gửi: Ban Giám hiệu Trường {school or '...'} và Sở Giáo dục & Đào tạo",
               size=12, align="left", space_after=8)

    # ── I. THÔNG TIN CHUNG ────────────────────────────────────────────────────
    _docx_para(doc, "I. THÔNG TIN CHUNG", bold=True, size=13, space_before=6, space_after=4)

    info_rows = [
        ("1. Cơ sở giáo dục",       school or "(chưa nhập)"),
        ("2. Cấp học",               level_key),
        ("3. Ngày kiểm tra",         date_str),
        ("4. Người kiểm tra",        insp or "(chưa nhập)"),
        ("5. Thực đơn hôm nay",      menu or "(chưa nhập)"),
        ("6. Mức cảnh báo",          f"{a.get('icon','')} {a.get('label','')}"),
        ("7. Kết quả tổng quát",     f"{pass_count} ĐẠT / {pass_count+fail_count} điểm đã kiểm tra"),
    ]
    t = doc.add_table(rows=len(info_rows), cols=2)
    t.style = "Table Grid"
    for i, (k, v) in enumerate(info_rows):
        r0 = t.rows[i].cells[0].paragraphs[0].add_run(k)
        r1 = t.rows[i].cells[1].paragraphs[0].add_run(v)
        _docx_set_font(r0, bold=True, size_pt=11)
        _docx_set_font(r1, size_pt=11)
        t.rows[i].cells[0].width = Cm(6)
        t.rows[i].cells[1].width = Cm(10)
    doc.add_paragraph()

    # ── II. CĂN CỨ PHÁP LÝ ───────────────────────────────────────────────────
    _docx_para(doc, "II. CĂN CỨ PHÁP LÝ", bold=True, size=13, space_before=6, space_after=4)
    legal_refs = [
        "Nghị định số 15/2018/NĐ-CP ngày 02/02/2018 của Chính phủ — Quy định chi tiết thi hành một số điều của Luật An toàn thực phẩm;",
        "Thông tư liên tịch số 13/2016/TTLT-BYT-BGDĐT ngày 12/5/2016 — Quy định về công tác y tế trường học;",
        "Quyết định số 3958/QĐ-BYT ngày 25/12/2025 của Bộ Y tế — Hướng dẫn dinh dưỡng bữa ăn học đường;",
        "QCVN 8-1:2011/BYT — Quy chuẩn kỹ thuật quốc gia về giới hạn ô nhiễm vi sinh vật trong thực phẩm;",
        "QCVN 8-2:2011/BYT — Quy chuẩn kỹ thuật quốc gia về giới hạn ô nhiễm kim loại nặng trong thực phẩm;",
        "Luật An toàn thực phẩm số 55/2010/QH12 ngày 17/6/2010 của Quốc hội.",
    ]
    for ref in legal_refs:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(ref)
        _docx_set_font(r, size_pt=11)
        p.paragraph_format.space_after = Pt(3)

    # ── III. KẾT QUẢ KIỂM TRA ────────────────────────────────────────────────
    _docx_para(doc, "III. KẾT QUẢ KIỂM TRA CHI TIẾT",
               bold=True, size=13, space_before=8, space_after=4)

    # Bảng chi tiết
    item_map = {code: (desc, is_crit, grp)
                for grp, items in cl for code, is_crit, desc, *_ in items}
    headers = ["Mã", "Bắt buộc", "Nội dung kiểm tra", "Kết quả", "Ghi chú"]
    tbl = doc.add_table(rows=1 + len(results), cols=5)
    tbl.style = "Table Grid"
    _docx_table_header(tbl, headers)

    col_widths = [Cm(1.2), Cm(1.8), Cm(8.5), Cm(2.5), Cm(3.0)]
    for i, (code, result) in enumerate(results.items()):
        if code not in item_map:
            continue
        desc, is_crit, _ = item_map[code]
        row = tbl.rows[i + 1]
        cells_data = [
            code,
            "★ Bắt buộc" if is_crit else "",
            desc,
            result.replace("✅ Đạt", "ĐẠT").replace("❌ Không Đạt", "KHÔNG ĐẠT").replace("Chưa chấm", "—"),
            notes.get(code, ""),
        ]
        for j, (cell, val, w) in enumerate(zip(row.cells, cells_data, col_widths)):
            cell.width = w
            is_fail = result == "❌ Không Đạt" and j == 3
            r = cell.paragraphs[0].add_run(val)
            _docx_set_font(r, bold=(j == 3 and is_fail), size_pt=10,
                           color=(192, 0, 0) if is_fail else None)
    doc.add_paragraph()

    # ── IV. ĐÁNH GIÁ VÀ NHẬN XÉT (AI narrative) ─────────────────────────────
    _docx_para(doc, "IV. ĐÁNH GIÁ VÀ NHẬN XÉT",
               bold=True, size=13, space_before=8, space_after=4)
    if ai_narrative and ai_narrative.startswith("(Không"):
        _docx_para(doc, "(Chưa tạo tóm tắt AI — vui lòng kết nối API key)",
                   size=11, align="justify")
    else:
        _docx_para(doc, ai_narrative or "(Chưa có đánh giá AI)",
                   size=12, align="justify", space_after=6)

    # Kết quả phân tích ảnh AI (nếu có)
    if photo_analysis:
        _docx_para(doc, "Kết quả phân tích ảnh minh chứng (AI):",
                   bold=True, size=12, space_before=4, space_after=2)
        RISK_VN = {"OK": "ĐẠT CHUẨN", "WARNING": "CẦN CHÚ Ý",
                   "CRITICAL": "NGUY HIỂM", "ERROR": "Không xác định"}
        for idx, (g_idx, r) in enumerate(photo_analysis.items()):
            lvl = r.get("risk_level", "OK")
            _docx_para(doc,
                       f"  • Nhóm {g_idx+1}: {RISK_VN.get(lvl, lvl)} "
                       f"(tin cậy {int(r.get('confidence',0.8)*100)}%) "
                       f"— {r.get('legal_ref','')}",
                       size=11, space_after=2)
            for issue in r.get("issues", []):
                _docx_para(doc, f"      → Vấn đề: {issue}", size=10, space_after=1)

    # ── V. KIẾN NGHỊ ─────────────────────────────────────────────────────────
    _docx_para(doc, "V. KIẾN NGHỊ VÀ YÊU CẦU XỬ LÝ",
               bold=True, size=13, space_before=8, space_after=4)
    fail_items = {c: v for c, v in results.items() if v == "❌ Không Đạt"}
    critical_fails = CRITICAL_ITEMS & set(fail_items.keys())

    if critical_fails:
        _docx_para(doc,
                   "1. YÊU CẦU KHẨN: Các mục bắt buộc dưới đây vi phạm — "
                   "đề nghị xử lý ngay trước bữa ăn tiếp theo:",
                   bold=True, size=12, space_after=2)
        for code in sorted(critical_fails):
            desc = item_map.get(code, ("",))[0]
            _docx_para(doc, f"   • {code}: {desc}", size=11, space_after=2)

    non_crit_fails = set(fail_items.keys()) - critical_fails
    if non_crit_fails:
        n = 2 if critical_fails else 1
        _docx_para(doc,
                   f"{n}. Các mục cần cải thiện trong 24 giờ:",
                   bold=True, size=12, space_after=2)
        for code in sorted(non_crit_fails):
            desc = item_map.get(code, ("",))[0]
            note = notes.get(code, "")
            _docx_para(doc,
                       f"   • {code}: {desc}" + (f" ({note})" if note else ""),
                       size=11, space_after=2)

    if not fail_items:
        _docx_para(doc,
                   "Bữa ăn đạt toàn bộ tiêu chí kiểm tra. "
                   "Đề nghị duy trì và tiếp tục theo dõi định kỳ.",
                   size=12, space_after=4)

    # ── VI. KẾT LUẬN ─────────────────────────────────────────────────────────
    _docx_para(doc, "VI. KẾT LUẬN", bold=True, size=13, space_before=8, space_after=4)
    _docx_para(doc,
               f"Trên đây là báo cáo kết quả kiểm tra An toàn thực phẩm bữa ăn học đường "
               f"tại {school or 'cơ sở giáo dục'} ngày {date_str}. "
               f"Tổng điểm đạt: {pass_count}/{pass_count+fail_count} điểm. "
               f"Đánh giá tổng thể: {a.get('label','—')}. "
               f"Báo cáo này được lập theo đúng quy định của TTLT 13/2016/TTLT-BYT-BGDĐT "
               f"và NĐ 15/2018/NĐ-CP.",
               size=12, align="justify", space_after=8)
    _docx_para(doc,
               "Kính đề nghị Ban Giám hiệu xem xét, chỉ đạo xử lý các vấn đề nêu trên "
               "và thông báo kết quả khắc phục cho Ban Giám sát trong vòng 24 giờ.",
               size=12, align="justify", space_after=16)

    # ── Chữ ký ───────────────────────────────────────────────────────────────
    sig_table = doc.add_table(rows=4, cols=2)
    sig_table.style = "Table Grid"
    sig_table.style = None  # Bỏ border cho bảng chữ ký

    left_cells = ["Đại diện Ban Giám sát PHHS", "", "", ""]
    right_cells = [f"TP. Hồ Chí Minh, {date_str}", "Người kiểm tra", "", f"{insp or '(ký và ghi rõ họ tên)'}"]
    for i, (lc, rc) in enumerate(zip(left_cells, right_cells)):
        for cell, txt, bold in [(sig_table.rows[i].cells[0], lc, i==0),
                                 (sig_table.rows[i].cells[1], rc, i in (0,1))]:
            r = cell.paragraphs[0].add_run(txt)
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_set_font(r, bold=bold, size_pt=12)

    # Ghi chú cuối trang
    doc.add_paragraph()
    _docx_para(doc,
               "─────────────────────────────────────────────────────",
               size=10, align="center", space_before=8, space_after=2)
    _docx_para(doc,
               f"Báo cáo được tạo tự động bởi SchoolFood AI v2.0 — {now_vn().strftime('%d/%m/%Y %H:%M')} (GMT+7)   |   "
               f"Đường dây nóng Cục ATTP: 1800 6838 (miễn phí)",
               size=9, align="center", space_after=0)

    # ── Xuất ra bytes ─────────────────────────────────────────────────────────
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def generate_word_incident(incident_log: list, school: str = "") -> bytes:
    """Tạo biên bản sự cố ngộ độc định dạng Word chuẩn hành chính."""
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from io import BytesIO

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(3.0); sec.right_margin = Cm(2.0)

    _docx_para(doc, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
               bold=True, size=13, align="center", space_after=2)
    _docx_para(doc, "Độc lập – Tự do – Hạnh phúc",
               bold=True, size=12, align="center", space_after=2)
    _docx_para(doc, "────────────────────────────────",
               size=11, align="center", space_after=4)
    _docx_para(doc, f"TP. Hồ Chí Minh, ngày {now_vn().strftime('%d tháng %m năm %Y')}",
               size=12, align="right", space_after=12)
    _docx_para(doc, "BIÊN BẢN SỰ CỐ AN TOÀN THỰC PHẨM",
               bold=True, size=14, align="center", space_after=2)
    _docx_para(doc, "Nghi ngờ ngộ độc thực phẩm tại cơ sở giáo dục",
               bold=True, size=13, align="center", space_after=12)
    _docx_para(doc, f"Cơ sở giáo dục: {school or '....................'}",
               size=12, space_after=4)
    _docx_para(doc, f"Thời gian lập biên bản: {now_vn().strftime('%H:%M ngày %d/%m/%Y')}",
               size=12, space_after=8)

    _docx_para(doc, "DIỄN BIẾN SỰ CỐ (TIMELINE):",
               bold=True, size=13, space_before=4, space_after=4)
    for entry in incident_log:
        _docx_para(doc, entry, size=12, align="justify", space_after=3)

    _docx_para(doc, "CĂN CỨ PHÁP LÝ ÁP DỤNG:",
               bold=True, size=13, space_before=8, space_after=4)
    for ref in [
        "TTLT 13/2016/TTLT-BYT-BGDĐT — Xử lý ngộ độc thực phẩm tập thể tại trường học",
        "NĐ 15/2018/NĐ-CP — Trách nhiệm báo cáo khi xảy ra ngộ độc thực phẩm",
        "Luật ATTP 55/2010/QH12 — Nghĩa vụ báo cáo cơ quan quản lý trong 24 giờ",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(ref); _docx_set_font(r, size_pt=11)
        p.paragraph_format.space_after = Pt(3)

    _docx_para(doc, "Đường dây nóng Cục ATTP: 1800 6838 (miễn phí)  |  Cấp cứu: 115",
               bold=True, size=12, align="center", space_before=8, space_after=16)

    for label in ["Đại diện Nhà trường", "Người lập biên bản", "Đại diện Ban Giám sát"]:
        p = doc.add_paragraph(f"{'':>40}{label}")
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.runs[0]; _docx_set_font(r, bold=True, size_pt=12)
        doc.add_paragraph()

    buf = BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


# ── AI #7: Trợ lý ứng phó sự cố ngộ độc ─────────────────────────────────────
def incident_ai_response(client: anthropic.Anthropic,
                          history: list, user_msg: str) -> str:
    """AI dẫn dắt xử lý sự cố ngộ độc từng bước, ghi nhận timeline."""
    INCIDENT_SYSTEM = """Bạn là chuyên gia ATTP khẩn cấp đang hỗ trợ xử lý sự cố ngộ độc thực phẩm học đường.
Nhiệm vụ: Dẫn dắt người dùng từng bước qua quy trình xử lý, hỏi thông tin còn thiếu, ghi nhận timeline.

QUY TRÌNH CHUẨN (TTLT 13/2016):
1. Dừng bữa ăn ngay
2. Gọi 115 nếu triệu chứng nặng (khó thở, co giật)
3. Giữ nguyên mẫu thức ăn (không vứt, không rửa)
4. Báo Hiệu trưởng + Y tế học đường ngay
5. Ghi chép số học sinh, triệu chứng, thời gian
6. Báo Sở Y tế trong 24h (bắt buộc nếu ≥2 người)

CÁCH PHẢN HỒI:
- Luôn xác nhận bước đã làm
- Hỏi thông tin cụ thể còn thiếu (số học sinh, triệu chứng, thời gian)
- Đưa ra bước tiếp theo rõ ràng
- Ghi nhận thông tin vào "SỔ GHI SỰ CỐ" format: [HH:MM] - nội dung
- Nếu tình huống nghiêm trọng (khó thở, co giật) → ưu tiên gọi 115 NGAY"""

    messages = history + [{"role": "user", "content": user_msg}]
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=INCIDENT_SYSTEM,
            messages=messages,
        )
        return resp.content[0].text
    except Exception as ex:
        return f"❌ Lỗi kết nối: {ex}"


# ── TAB 1: Hỏi đáp AI ─────────────────────────────────────────────────────────
def tab_chat(api_key, role, level, loc):
    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">💬 Hỏi đáp pháp luật ATTP</div>
        <div class="sf-card-body">Đặt câu hỏi bằng tiếng Việt thông thường — AI trả lời dựa trên văn bản pháp luật thực tế.</div>
    </div>""", unsafe_allow_html=True)

    QUICK = {
        "Phụ Huynh": [
            "Phụ Huynh có quyền vào bếp kiểm tra không?",
            "Con tôi đau bụng sau bữa trưa — tôi phải làm gì ngay?",
            "Làm sao biết suất ăn của con đủ dinh dưỡng không?",
            "Tôi có thể yêu cầu xem thực đơn trước không?",
        ],
        "Ban Giám Sát": [
            "Ban Giám Sát có quyền gì theo pháp luật?",
            "Phát hiện thực phẩm hết hạn — phải báo cáo ai?",
            "Nhà Cung Cấp cần có những giấy tờ gì?",
            "Tiêu chuẩn khẩu phần tiểu học theo quy định 2025?",
        ],
        "Y Tế Học Đường": [
            "Sổ kiểm thực 3 bước cần ghi những gì?",
            "Mẫu lưu thức ăn cần lưu bao lâu và cách nào?",
            "Nhiệt độ bảo quản đúng chuẩn cho từng loại thực phẩm?",
            "Quy trình xử lý khi nghi ngờ ngộ độc tập thể?",
        ],
        "Ban Giám Hiệu": [
            "Hiệu Trưởng chịu trách nhiệm pháp lý như thế nào?",
            "Tiêu chí lựa chọn Nhà Cung Cấp suất ăn hợp lệ?",
            "Mức xử phạt khi xảy ra ngộ độc thực phẩm tại trường?",
            "Báo cáo định kỳ ATTP gửi Sở GD&ĐT như thế nào?",
        ],
    }
    questions = QUICK.get(role, QUICK["Phụ Huynh"])
    st.markdown('<div class="sec-hdr">Câu hỏi phổ biến cho vai trò của bạn</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    for i, q in enumerate(questions):
        if (c1 if i % 2 == 0 else c2).button(q, key=f"qq{i}", use_container_width=True):
            st.session_state.preset_q = q

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    preset = st.session_state.pop("preset_q", None)
    user_input = st.chat_input("Nhập câu hỏi...") or preset
    if user_input:
        if not api_key:
            st.warning("⚠️ Vui lòng nhập API Key ở cài đặt trong sidebar.")
            st.stop()
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Đang tra cứu..."):
                sys = build_system_prompt(role, level, loc)
                hist = [{"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[:-1]]
                ans = ask_claude(anthropic.Anthropic(api_key=api_key), sys, hist, user_input)
                st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})
    if st.session_state.get("messages"):
        if st.button("🗑️ Xóa lịch sử", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


# ── TAB 2: Checklist ──────────────────────────────────────────────────────────
def tab_checklist(api_key: str = ""):
    ai_on = bool(api_key)   # AI features chỉ hoạt động khi có API key

    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">✅ Checklist kiểm tra ATTP bữa ăn học đường</div>
        <div class="sf-card-body">20 điểm chuẩn hoá · Mục <span style="background:#FEE2E2;color:#991B1B;padding:1px 6px;border-radius:8px;font-weight:700;font-size:0.75rem">BẮT BUỘC</span> phải đạt tuyệt đối
        """ + (" · <span style='color:#2563EB;font-weight:600'>🤖 AI đang hoạt động</span>" if ai_on else " · <i style='color:#94A3B8'>AI tắt — checklist vẫn dùng được đầy đủ</i>") + """
        </div>
    </div>""", unsafe_allow_html=True)

    # Chọn cấp học — ảnh hưởng C12, C13
    level_key = st.selectbox(
        "Cấp học đang kiểm tra (ảnh hưởng tiêu chuẩn dinh dưỡng C12, C13)",
        list(NUTRITION.keys()), key="cl_level",
    )
    n = NUTRITION[level_key]

    # Banner dinh dưỡng
    st.markdown(f"""<div class="nutrition-banner">
        <div class="nutrition-label">📊 Tiêu Chuẩn Dinh Dưỡng Bữa Trưa — Cấp {n['short']} (QĐ 3958/QĐ-BYT 2025)</div>
        <div class="nutrition-grid">
            <div class="nutrition-item">⚡ Năng lượng: <span class="nutrition-val">{n['kcal']}</span> ({n['pct_day']} nhu cầu ngày)</div>
            <div class="nutrition-item">🥩 Thịt/cá tối thiểu: <span class="nutrition-val">{n['meat_g']}g/học sinh</span></div>
            <div class="nutrition-item">🥦 Rau xanh: <span class="nutrition-val">{n['veg_range']}/học sinh</span></div>
            <div class="nutrition-item">💪 Protein: <span class="nutrition-val">{n['protein_pct']}</span> tổng năng lượng</div>
        </div>
        <div style="font-size:0.75rem;color:#1D4ED8;margin-top:6px">💡 {n['note']}</div>
    </div>""", unsafe_allow_html=True)

    # Thông tin kiểm tra
    st.markdown('<div class="sec-hdr">Thông tin buổi kiểm tra</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    school = c1.text_input("Tên trường", placeholder="VD: TH Nguyễn Du, Q.1")
    date   = c2.date_input("Ngày kiểm tra", value=datetime.today(), format="DD/MM/YYYY")
    insp   = c3.text_input("Người kiểm tra", placeholder="Họ và tên")
    menu   = st.text_input("Thực đơn hôm nay",
                            placeholder="VD: Cơm, thịt kho trứng, rau muống xào tỏi, canh chua cá")

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

    if "cl_r"       not in st.session_state: st.session_state.cl_r       = {}
    if "cl_n"       not in st.session_state: st.session_state.cl_n       = {}
    if "cl_photos"  not in st.session_state: st.session_state.cl_photos  = {}
    if "cl_extra"   not in st.session_state: st.session_state.cl_extra   = []
    if "photo_analysis" not in st.session_state: st.session_state.photo_analysis = {}

    # ── AI #1: Tạo checklist bổ sung theo thực đơn ───────────────────────────
    if ai_on and menu:
        col_btn, col_status = st.columns([0.4, 0.6])
        if col_btn.button("🤖 Tạo câu hỏi kiểm tra theo thực đơn",
                          use_container_width=True, key="gen_extra"):
            with st.spinner("AI đang phân tích thực đơn..."):
                extras = generate_extra_checklist(menu, level_key, api_key)
                st.session_state.cl_extra = extras
                st.session_state.photo_analysis = {}  # reset khi đổi thực đơn
        if st.session_state.cl_extra:
            col_status.markdown(
                f'<span style="color:#16A34A;font-size:0.85rem">✅ AI đã tạo '
                f'<b>{len(st.session_state.cl_extra)}</b> câu hỏi bổ sung</span>',
                unsafe_allow_html=True,
            )
    elif not ai_on and menu:
        st.caption("💡 Kết nối AI để tạo câu hỏi kiểm tra riêng theo thực đơn hôm nay.")

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    cl = get_checklist(level_key)

    # ── FIX: Pre-initialize TRƯỚC KHI render để tránh reset state khi rerun ──
    # Streamlit đọc session_state[key] để khôi phục giá trị widget.
    # Nếu key chưa tồn tại, widget dùng `default`. Nhưng nếu `default` được
    # truyền vào mỗi lần render, nó xung đột với giá trị đã lưu → bug reset.
    # Giải pháp: tạo key với "Chưa chấm" một lần duy nhất, không truyền default.
    for _, grp_items in cl:
        for item_code, *_ in grp_items:
            seg_key = f"seg_{item_code}"
            if seg_key not in st.session_state:
                st.session_state[seg_key] = "Chưa chấm"
            # Đồng bộ cl_r với widget state (nguồn sự thật là session_state[seg_key])
            st.session_state.cl_r[item_code] = st.session_state[seg_key]

    pass_count = fail_count = 0

    for g_idx, (group_name, items) in enumerate(cl):
        # Đếm trạng thái trong nhóm → hiển thị summary trên header
        g_codes   = [c for c, *_ in items]
        g_pass    = sum(1 for c in g_codes if st.session_state.cl_r.get(c) == "✅ Đạt")
        g_fail    = sum(1 for c in g_codes if st.session_state.cl_r.get(c) == "❌ Không Đạt")
        g_pending = len(g_codes) - g_pass - g_fail
        summary_parts = []
        if g_pass:    summary_parts.append(f'<span style="color:#16A34A;font-weight:700">✅ {g_pass} đạt</span>')
        if g_fail:    summary_parts.append(f'<span style="color:#DC2626;font-weight:700">❌ {g_fail} không đạt</span>')
        if g_pending: summary_parts.append(f'<span style="color:#D97706">○ {g_pending} chưa chấm</span>')
        summary_html = (
            '<span style="font-size:0.72rem;margin-left:10px;font-weight:500">'
            + ' &nbsp;·&nbsp; '.join(summary_parts) + '</span>'
        )
        st.markdown(
            f'<div class="group-title">{group_name}{summary_html}</div>',
            unsafe_allow_html=True,
        )

        for (code, is_critical, desc, how, pass_cond, fail_cond) in items:
            # Đọc trạng thái hiện tại của item → màu row thay đổi realtime
            cur_state = st.session_state.cl_r.get(code, "Chưa chấm")
            if cur_state == "✅ Đạt":
                row_left = "#16A34A"; row_bg = "#F0FDF4"
                code_clr = "#166534"; code_icon = "✅"
                state_label = '<span style="font-size:0.7rem;font-weight:700;color:#16A34A;margin-left:6px">ĐẠT</span>'
            elif cur_state == "❌ Không Đạt":
                row_left = "#DC2626"; row_bg = "#FFF5F5"
                code_clr = "#991B1B"; code_icon = "❌"
                state_label = '<span style="font-size:0.7rem;font-weight:700;color:#DC2626;margin-left:6px">KHÔNG ĐẠT</span>'
            else:
                row_left = "#F59E0B"; row_bg = "#FFFBEB"
                code_clr = "#D97706"; code_icon = "○"
                state_label = '<span style="font-size:0.7rem;color:#D97706;margin-left:6px">chưa chấm</span>'

            crit_badge = (
                '<span style="background:#FEE2E2;color:#991B1B;font-size:0.65rem;'
                'font-weight:700;padding:1px 6px;border-radius:8px;margin-left:6px;'
                'border:1px solid #FECACA">BẮT BUỘC</span>'
            ) if is_critical else ""

            col_desc, col_ctrl = st.columns([0.62, 0.38])

            with col_desc:
                st.markdown(
                    f'<div style="background:{row_bg};border-left:3px solid {row_left};'
                    f'border-radius:0 8px 8px 0;padding:10px 14px;margin:3px 0;'
                    f'transition:background 0.4s ease,border-color 0.4s ease">'
                    f'<div style="margin-bottom:4px;display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
                    f'<span style="font-size:0.72rem;font-weight:800;color:{code_clr}">'
                    f'{code_icon} {code}</span>'
                    f'{crit_badge}{state_label}'
                    f'</div>'
                    f'<div style="font-size:0.88rem;font-weight:500;color:#1E293B;line-height:1.55">'
                    f'{desc}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("🔍 Hướng dẫn kiểm tra"):
                    st.markdown(
                        f"**Thực hiện:** {how}  \n"
                        f"**✅ Đạt khi:** {pass_cond}  \n"
                        f"**❌ Không đạt khi:** {fail_cond}"
                    )

            with col_ctrl:
                # Không truyền default= — giá trị được khôi phục từ session_state
                st.segmented_control(
                    label=code,
                    options=["Chưa chấm", "✅ Đạt", "❌ Không Đạt"],
                    key=f"seg_{code}",
                    label_visibility="collapsed",
                )
                # Đọc lại từ session_state sau khi widget render
                result = st.session_state.get(f"seg_{code}", "Chưa chấm")
                st.session_state.cl_r[code] = result

                note = st.text_input(
                    label=f"ghi_chú_{code}", label_visibility="collapsed",
                    placeholder="Ghi chú (nếu có)...", key=f"note_{code}",
                )
                st.session_state.cl_n[code] = note

            if result == "✅ Đạt":
                pass_count += 1
            elif result == "❌ Không Đạt":
                fail_count += 1

        # ── Ảnh minh chứng + AI phân tích ────────────────────────────────────
        with st.expander(f"📷 Ảnh minh chứng — {group_name}"
                         + (" · 🤖 AI phân tích" if ai_on else "")):
            photo_col1, photo_col2 = st.columns(2)
            with photo_col1:
                st.caption("📱 Chụp ảnh (camera)")
                cam = st.camera_input("Chụp ảnh", key=f"cam_{g_idx}",
                                      label_visibility="collapsed")
                if cam:
                    st.session_state.cl_photos[f"cam_{g_idx}"] = cam
                    st.success("✅ Đã lưu ảnh chụp")
            with photo_col2:
                st.caption("💻 Tải ảnh từ máy")
                upl = st.file_uploader(
                    "Tải ảnh", type=["jpg", "jpeg", "png", "heic"],
                    key=f"upl_{g_idx}", label_visibility="collapsed",
                    accept_multiple_files=True,
                )
                if upl:
                    st.session_state.cl_photos[f"upl_{g_idx}"] = upl
                    st.success(f"✅ Đã tải {len(upl)} ảnh")

            # ── AI #2: Nút phân tích ảnh ──────────────────────────────────
            active_photo = (
                st.session_state.cl_photos.get(f"cam_{g_idx}") or
                (st.session_state.cl_photos.get(f"upl_{g_idx}") or [None])[0]
            )
            if ai_on and active_photo:
                if st.button(f"🔍 Phân tích ảnh với AI", key=f"analyze_{g_idx}",
                             use_container_width=True):
                    with st.spinner("AI đang phân tích ảnh..."):
                        photo_bytes = (active_photo.read()
                                       if hasattr(active_photo, "read")
                                       else active_photo.getvalue())
                        result = analyze_photo_ai(photo_bytes, group_name, api_key)
                        st.session_state.photo_analysis[g_idx] = result

                # Hiển thị kết quả phân tích
                if g_idx in st.session_state.photo_analysis:
                    r = st.session_state.photo_analysis[g_idx]
                    lvl  = r.get("risk_level", "OK")
                    clr  = {"OK": "#16A34A", "WARNING": "#D97706",
                            "CRITICAL": "#DC2626", "ERROR": "#64748B"}.get(lvl, "#64748B")
                    bg   = {"OK": "#F0FDF4", "WARNING": "#FFFBEB",
                            "CRITICAL": "#FEF2F2", "ERROR": "#F8FAFC"}.get(lvl, "#F8FAFC")
                    icon = {"OK": "✅", "WARNING": "⚠️",
                            "CRITICAL": "🚨", "ERROR": "❓"}.get(lvl, "❓")
                    conf = int(r.get("confidence", 0.8) * 100)

                    issues_html = "".join(
                        f"<li style='color:#DC2626'>{i}</li>" for i in r.get("issues", [])
                    ) or ""
                    pos_html = "".join(
                        f"<li style='color:#16A34A'>{p}</li>" for p in r.get("positives", [])
                    ) or ""

                    st.markdown(f"""
                    <div style="background:{bg};border-left:4px solid {clr};
                                border-radius:8px;padding:12px 16px;margin-top:8px">
                        <div style="font-weight:700;color:{clr};margin-bottom:6px">
                            {icon} Kết quả AI: <b>{lvl}</b>
                            <span style="font-weight:400;font-size:0.75rem;
                                         color:#64748B;margin-left:8px">
                                Độ tin cậy: {conf}%</span>
                        </div>
                        {"<ul style='margin:4px 0;padding-left:16px'>" + issues_html + "</ul>" if issues_html else ""}
                        {"<ul style='margin:4px 0;padding-left:16px'>" + pos_html + "</ul>" if pos_html else ""}
                        {"<div style='font-size:0.82rem;color:#475569;margin-top:6px'><b>Khuyến nghị:</b> " + r.get("recommendation","") + "</div>" if r.get("recommendation") else ""}
                    </div>""", unsafe_allow_html=True)
            elif not ai_on and active_photo:
                st.caption("💡 Kết nối AI để phân tích ảnh tự động.")

        st.markdown("<br>", unsafe_allow_html=True)

    # ── Kết quả & Cảnh báo ───────────────────────────────────────────────────
    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">Kết quả tổng hợp</div>', unsafe_allow_html=True)

    total_answered = pass_count + fail_count
    critical_fails = CRITICAL_ITEMS & {c for c, v in st.session_state.cl_r.items() if v == "❌ Không Đạt"}

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">Đã kiểm tra</div>
        <div class="metric-num c-blue">{total_answered}</div>
        <div class="metric-lbl">/ {TOTAL_ITEMS} điểm</div>
    </div>""", unsafe_allow_html=True)
    m2.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">✅ Đạt</div>
        <div class="metric-num c-green">{pass_count}</div>
        <div class="metric-lbl">điểm</div>
    </div>""", unsafe_allow_html=True)
    m3.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">❌ Không Đạt</div>
        <div class="metric-num c-red">{fail_count}</div>
        <div class="metric-lbl">điểm</div>
    </div>""", unsafe_allow_html=True)
    crit_color = "c-red" if critical_fails else "c-green"
    crit_num   = str(len(critical_fails)) if critical_fails else "✓"
    crit_sub   = "vi phạm" if critical_fails else "Tất cả đạt"
    m4.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">Mục bắt buộc</div>
        <div class="metric-num {crit_color}">{crit_num}</div>
        <div class="metric-lbl">{crit_sub} / {len(CRITICAL_ITEMS)} mục</div>
    </div>""", unsafe_allow_html=True)
    pct = int(pass_count / total_answered * 100) if total_answered else 0
    pct_color = "c-green" if pct >= 90 else "c-orange" if pct >= 75 else "c-red"
    m5.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">Tỷ lệ đạt</div>
        <div class="metric-num {pct_color}">{pct}%</div>
        <div class="metric-lbl">trong số đã chấm</div>
    </div>""", unsafe_allow_html=True)

    # Alert level
    if total_answered >= 10:
        alert_key = determine_alert(st.session_state.cl_r, cl)
        a = ALERT_SYSTEM[alert_key]
        css_cls = f"alert-{alert_key.lower()}"
        notify_html = "".join(f"<li>{n}</li>" for n in a["notify"])
        st.markdown(f"""
        <div class="{css_cls}" style="margin-top:16px">
            <div class="alert-title" style="color:{a['color']}">{a['icon']} {a['label']}</div>
            <div class="alert-body">
                <b>Hành động:</b> {a['action']}<br><br>
                <b>Thông báo đến:</b>
                <ul style="margin:4px 0 0 16px;padding:0">{notify_html}</ul>
                <b>Thời hạn:</b> {a['timeframe']}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if critical_fails:
            codes_str = ", ".join(sorted(critical_fails))
            st.error(f"🚨 Mục bắt buộc vi phạm: **{codes_str}** — Xem lại ngay và báo Ban Giám Hiệu!")

    # ── Thanh tiến độ hoàn thành ─────────────────────────────────────────────
    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    answered_count = sum(1 for v in st.session_state.cl_r.values() if v != "Chưa chấm")
    pct_done = int(answered_count / TOTAL_ITEMS * 100)
    bar_color = "#16A34A" if pct_done == 100 else "#2563EB" if pct_done >= 50 else "#F59E0B"
    remaining  = TOTAL_ITEMS - answered_count
    done_label = "✅ Đã hoàn thành toàn bộ!" if remaining == 0 else f"Còn {remaining} mục chưa đánh giá"
    st.markdown(f"""
    <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
            <span style="font-size:0.82rem;font-weight:600;color:#334155">
                Tiến độ đánh giá: {answered_count}/{TOTAL_ITEMS} mục
            </span>
            <span style="font-size:0.8rem;color:{'#16A34A' if remaining==0 else '#D97706'};font-weight:600">
                {done_label}
            </span>
        </div>
        <div class="completion-bar-wrap">
            <div class="completion-bar-fill"
                 style="width:{pct_done}%;background:{bar_color}"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Validation trước khi xuất báo cáo ────────────────────────────────────
    errors = validate_checklist(st.session_state.cl_r, st.session_state.cl_photos)
    if errors:
        err_html = "".join(f'<div class="validation-item">⚠️ {e}</div>' for e in errors)
        st.markdown(f"""
        <div class="validation-box">
            <div class="validation-title">⛔ Chưa thể xuất báo cáo — Cần hoàn thành các mục sau:</div>
            {err_html}
        </div>
        """, unsafe_allow_html=True)

    can_submit = len(errors) == 0

    # ── Hiển thị checklist bổ sung từ AI (nếu có) ────────────────────────────
    if st.session_state.cl_extra:
        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="sec-hdr">🤖 Câu hỏi bổ sung AI ({len(st.session_state.cl_extra)} câu) — theo thực đơn hôm nay</div>',
            unsafe_allow_html=True,
        )
        if "cl_extra_r" not in st.session_state:
            st.session_state.cl_extra_r = {}
        for item in st.session_state.cl_extra:
            code = item.get("code", "?")
            desc = item.get("desc", "")
            ingr = item.get("ingredient", "")
            why  = item.get("why", "")
            col_d, col_c = st.columns([0.65, 0.35])
            with col_d:
                st.markdown(
                    f'<div style="background:#EFF6FF;border-left:3px solid #2563EB;'
                    f'border-radius:0 8px 8px 0;padding:8px 14px;margin:3px 0">'
                    f'<span style="font-size:0.7rem;font-weight:800;color:#2563EB">'
                    f'🤖 {code}</span>'
                    f'<span style="font-size:0.72rem;color:#1D4ED8;margin-left:6px;'
                    f'background:#DBEAFE;padding:1px 6px;border-radius:8px">{ingr}</span>'
                    f'<div style="font-size:0.88rem;font-weight:500;color:#1E293B;'
                    f'margin-top:4px">{desc}</div>'
                    f'{"<div style=font-size:0.75rem;color:#64748B;margin-top:2px>" + why + "</div>" if why else ""}'
                    f'</div>', unsafe_allow_html=True,
                )
                with st.expander("Hướng dẫn"):
                    st.markdown(
                        f"**Kiểm tra:** {item.get('how','')}  \n"
                        f"**✅ Đạt:** {item.get('pass','')}  \n"
                        f"**❌ Không đạt:** {item.get('fail','')}"
                    )
            with col_c:
                seg_key = f"seg_extra_{code}"
                if seg_key not in st.session_state:
                    st.session_state[seg_key] = "Chưa chấm"
                st.segmented_control(
                    code, ["Chưa chấm", "✅ Đạt", "❌ Không Đạt"],
                    key=seg_key, label_visibility="collapsed",
                )
                st.session_state.cl_extra_r[code] = \
                    st.session_state.get(seg_key, "Chưa chấm")
        if st.button("🗑️ Xoá câu hỏi AI", use_container_width=True):
            st.session_state.cl_extra = []
            st.rerun()

    # ── Nút tạo báo cáo ──────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(
        "📄 Tạo báo cáo kiểm tra" if can_submit else "⛔ Hoàn thành đủ 20 mục để xuất báo cáo",
        type="primary" if can_submit else "secondary",
        disabled=not can_submit,
        use_container_width=True,
    ):
        alert_key = determine_alert(st.session_state.cl_r, cl)
        date_vn   = date.strftime("%d/%m/%Y")
        report    = _build_report(school, date_vn, insp, menu, level_key,
                                  st.session_state.cl_r, st.session_state.cl_n,
                                  pass_count, fail_count, alert_key, cl)
        photo_count = sum(
            (len(v) if isinstance(v, list) else 1)
            for v in st.session_state.cl_photos.values() if v
        )

        # ── AI #3: Tóm tắt ngôn ngữ tự nhiên ────────────────────────────────
        if ai_on:
            with st.spinner("🤖 AI đang viết tóm tắt báo cáo..."):
                narrative = generate_ai_narrative(
                    st.session_state.cl_r, st.session_state.cl_n,
                    alert_key, school, date_vn, menu,
                    pass_count, pass_count + fail_count, level_key, api_key,
                )
                a = ALERT_SYSTEM.get(alert_key, {})
                st.markdown(f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;
                            border-radius:10px;padding:16px 20px;margin-bottom:12px">
                    <div style="font-size:0.75rem;font-weight:700;color:#2563EB;
                                margin-bottom:8px">🤖 TÓM TẮT BÁO CÁO — AI tạo tự động</div>
                    <div style="font-size:0.9rem;color:#1E293B;line-height:1.7">{narrative}</div>
                </div>""", unsafe_allow_html=True)
                report = f"TÓM TẮT (AI):\n{narrative}\n\n{'='*64}\n\n" + report

        if photo_count:
            st.info(f"📷 Kèm {photo_count} ảnh + "
                    f"{len(st.session_state.photo_analysis)} kết quả phân tích AI")

        # ── Tải báo cáo Word (.docx) ─────────────────────────────────────────
        with st.spinner("⚙️ Đang tạo file Word..."):
            docx_bytes = generate_word_report(
                school, date_vn, insp, menu, level_key,
                st.session_state.cl_r, st.session_state.cl_n,
                pass_count, fail_count, alert_key, cl,
                narrative if ai_on else "",
                st.session_state.photo_analysis,
            )
        fname_docx = f"BaoCao_ATTP_{(school or 'Truong').replace(' ','_')}_{date.strftime('%d-%m-%Y')}.docx"
        st.download_button(
            "⬇️ Tải báo cáo Word (.docx) — Times New Roman, chuẩn hành chính",
            data=docx_bytes, file_name=fname_docx,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, type="primary",
        )
        # Vẫn giữ txt để xem nhanh
        with st.expander("Xem trước nội dung (text)"):
            st.text(report)


def _build_report(school, date, insp, menu, level_key, results, notes,
                  pass_count, fail_count, alert_key, cl) -> str:
    a = ALERT_SYSTEM.get(alert_key, {})
    lines = [
        "=" * 64,
        "   BÁO CÁO KIỂM TRA AN TOÀN THỰC PHẨM BỮA ĂN HỌC ĐƯỜNG",
        "=" * 64,
        f"   Trường          : {school or '(chưa nhập)'}",
        f"   Cấp học         : {level_key}",
        f"   Ngày kiểm tra   : {date}",
        f"   Người kiểm tra  : {insp or '(chưa nhập)'}",
        f"   Thực đơn        : {menu or '(chưa nhập)'}",
        f"   Thời gian tạo   : {now_vn().strftime('%d/%m/%Y %H:%M')}",
        "",
        f"   KẾT QUẢ   : {pass_count} ĐẠT / {pass_count + fail_count} điểm đã kiểm tra",
        f"   MỨC CẢNH BÁO: {a.get('icon','')} {a.get('label','—')}",
        f"   HÀNH ĐỘNG : {a.get('action','—')}",
        "",
        "-" * 64,
        "   CHI TIẾT TỪNG ĐIỂM KIỂM TRA",
        "-" * 64,
    ]
    item_map = {
        code: (desc, is_crit, group)
        for group, items in cl
        for (code, is_crit, desc, *_) in items
    }
    cur_grp = None
    for code, result in results.items():
        if code not in item_map:
            continue
        desc, is_crit, grp = item_map[code]
        if grp != cur_grp:
            cur_grp = grp
            lines += ["", f"   [ {grp} ]"]
        crit = " [BẮT BUỘC]" if is_crit else ""
        status = result.replace("✅ Đạt", "ĐẠT").replace("❌ Không Đạt", "KHÔNG ĐẠT").replace("Chưa chấm", "—")
        note = notes.get(code, "")
        note_str = f"  → {note}" if note else ""
        lines.append(f"   {code}{crit:<12} [{status:<12}] {desc}{note_str}")

    notify_str = "\n".join(f"     • {n}" for n in a.get("notify", []))
    lines += [
        "", "-" * 64,
        "   THÔNG BÁO ĐẾN:", notify_str,
        "", "-" * 64,
        "   Căn cứ pháp lý:",
        "     • NĐ 15/2018/NĐ-CP — Điều kiện ATTP cơ sở kinh doanh thực phẩm",
        "     • TTLT 13/2016/TTLT-BYT-BGDĐT — Y tế trường học",
        "     • QĐ 3958/QĐ-BYT 2025 — Dinh dưỡng bữa ăn học đường",
        "     • Đường dây nóng Cục ATTP: 1800 6838 (miễn phí)",
        "-" * 64,
        "   Ký tên người kiểm tra: _____________________________",
        "   SchoolFood AI v1.1",
        "=" * 64,
    ]
    return "\n".join(lines)


# ── TAB 3: Lịch & Thông báo ───────────────────────────────────────────────────
def tab_schedule():
    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">📅 Tần Suất Kiểm Tra & Hệ Thống Thông Báo</div>
        <div class="sf-card-body">Quy định rõ ai kiểm tra gì, khi nào, báo cáo ai — để không có khoảng trống trách nhiệm.</div>
    </div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">Lịch kiểm tra theo vai trò</div>', unsafe_allow_html=True)

    for s in SCHEDULE:
        st.markdown(f"""
        <div class="schedule-card" style="--sc-color:{s['color']}">
            <div class="schedule-role">{s['role']}</div>
            <div class="schedule-row"><span class="schedule-key">🔁 Tần suất:</span> {s['freq']}</div>
            <div class="schedule-row"><span class="schedule-key">⏰ Thời điểm:</span> {s['when']}</div>
            <div class="schedule-row"><span class="schedule-key">📋 Nội dung:</span> {s['what']}</div>
            <div class="schedule-row"><span class="schedule-key">📢 Báo trước:</span> {s['notice']}</div>
            <div class="schedule-row"><span class="schedule-key">📤 Báo cáo:</span> {s['report']}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">Hệ thống cảnh báo theo cấp độ</div>', unsafe_allow_html=True)

    for key, a in ALERT_SYSTEM.items():
        triggers_html = "".join(f"<li>{t}</li>" for t in a["triggers"])
        notify_html   = "".join(f"<li>{n}</li>" for n in a["notify"])
        css_cls = f"alert-{key.lower()}"
        st.markdown(f"""
        <div class="{css_cls}" style="margin-bottom:12px">
            <div class="alert-title" style="color:{a['color']}">{a['icon']} {a['label']}</div>
            <div class="alert-body">
                <b>Kích hoạt khi:</b>
                <ul style="margin:4px 0 8px 16px;padding:0">{triggers_html}</ul>
                <b>Thông báo đến:</b>
                <ul style="margin:4px 0 8px 16px;padding:0">{notify_html}</ul>
                <b>Thời hạn xử lý:</b> {a['timeframe']}<br>
                <b>Hành động:</b> {a['action']}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">Tiêu chí đánh giá tổng thể</div>', unsafe_allow_html=True)

    st.markdown("""<div class="sf-card">
    <table style="width:100%;border-collapse:collapse;font-size:0.875rem">
    <tr style="background:#F8FAFC;font-weight:600;color:#475569">
        <td style="padding:10px 14px;border-bottom:2px solid #E2E8F0">Điều kiện</td>
        <td style="padding:10px 14px;border-bottom:2px solid #E2E8F0">Kết quả</td>
        <td style="padding:10px 14px;border-bottom:2px solid #E2E8F0">Mức cảnh báo</td>
    </tr>
    <tr>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9">Có bất kỳ mục BẮT BUỘC nào không đạt</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#DC2626;font-weight:600">Tạm dừng bữa ăn</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9"><span style="background:#FEE2E2;color:#991B1B;padding:2px 8px;border-radius:8px;font-size:0.78rem;font-weight:700">🔴 CRITICAL</span></td>
    </tr>
    <tr style="background:#FAFAFA">
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9">Tổng điểm đạt dưới 15/20</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#D97706;font-weight:600">Khắc phục trong ngày</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9"><span style="background:#FEF9C3;color:#854D0E;padding:2px 8px;border-radius:8px;font-size:0.78rem;font-weight:700">🟠 MAJOR</span></td>
    </tr>
    <tr>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9">Tổng điểm đạt 15–17/20</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#CA8A04;font-weight:600">Cải thiện trong tuần</td>
        <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9"><span style="background:#FEFCE8;color:#854D0E;padding:2px 8px;border-radius:8px;font-size:0.78rem;font-weight:700">🟡 MINOR</span></td>
    </tr>
    <tr style="background:#FAFAFA">
        <td style="padding:10px 14px">Tất cả mục BẮT BUỘC đạt + Tổng ≥ 18/20</td>
        <td style="padding:10px 14px;color:#16A34A;font-weight:600">Lưu hồ sơ bình thường</td>
        <td style="padding:10px 14px"><span style="background:#DCFCE7;color:#166534;padding:2px 8px;border-radius:8px;font-size:0.78rem;font-weight:700">✅ ĐẠT CHUẨN</span></td>
    </tr>
    </table>
    <div style="font-size:0.78rem;color:#94A3B8;margin-top:12px">
        * 7 mục BẮT BUỘC: C03 (hạn dùng) · C07 (nhiệt độ nhận) · C09 (nhiệt độ chia) · C10 (thời gian nấu) · C11 (màu/mùi) · C18 (sổ kiểm thực) · C20 (mẫu lưu)
    </div>
    </div>""", unsafe_allow_html=True)


# ── TAB 4: Khẩn cấp ──────────────────────────────────────────────────────────
def tab_emergency(api_key: str = ""):
    st.markdown('<div class="emergency-header">🚨 XỬ LÝ KHẨN CẤP KHI NGHI NGỜ NGỘ ĐỘC THỰC PHẨM</div>',
                unsafe_allow_html=True)

    # ── AI #7: Chế độ ứng phó sự cố trực tiếp ───────────────────────────────
    if api_key:
        st.markdown("""<div class="sf-card" style="border:2px solid #DC2626">
            <div class="sf-card-title" style="color:#DC2626">
                🤖 Chế độ ứng phó sự cố — AI hỗ trợ trực tiếp
            </div>
            <div class="sf-card-body">
                AI sẽ hỏi từng bước, ghi nhận timeline và tạo biên bản sự cố tự động.
            </div>
        </div>""", unsafe_allow_html=True)

        if "incident_active" not in st.session_state:
            st.session_state.incident_active = False
        if "incident_history" not in st.session_state:
            st.session_state.incident_history = []
        if "incident_log" not in st.session_state:
            st.session_state.incident_log = []

        col_start, col_end = st.columns(2)
        if col_start.button("🚨 Bắt đầu xử lý sự cố", type="primary",
                            use_container_width=True,
                            disabled=st.session_state.incident_active):
            st.session_state.incident_active = True
            st.session_state.incident_history = []
            st.session_state.incident_log = [
                f"[{now_vn().strftime('%H:%M')}] — Bắt đầu ghi nhận sự cố"
            ]
            st.rerun()

        if col_end.button("⏹ Kết thúc & Tạo biên bản", use_container_width=True,
                          disabled=not st.session_state.incident_active):
            st.session_state.incident_active = False
            st.rerun()

        if st.session_state.incident_active:
            st.error("🔴 **ĐANG XỬ LÝ SỰ CỐ** — Trả lời AI từng bước")

            for msg in st.session_state.incident_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # Khởi động với câu hỏi đầu tiên
            if not st.session_state.incident_history:
                client  = anthropic.Anthropic(api_key=api_key)
                opening = incident_ai_response(client, [],
                    "Tôi nghi ngờ có học sinh bị ngộ độc thực phẩm sau bữa ăn. Tôi cần làm gì?")
                st.session_state.incident_history.append(
                    {"role": "assistant", "content": opening})
                st.rerun()

            user_msg = st.chat_input("Mô tả tình huống...", key="incident_input")
            if user_msg:
                st.session_state.incident_history.append(
                    {"role": "user", "content": user_msg})
                st.session_state.incident_log.append(
                    f"[{now_vn().strftime('%H:%M')}] Người dùng: {user_msg}")
                client = anthropic.Anthropic(api_key=api_key)
                with st.spinner("AI đang phân tích..."):
                    ai_reply = incident_ai_response(
                        client,
                        [{"role": m["role"], "content": m["content"]}
                         for m in st.session_state.incident_history[:-1]],
                        user_msg,
                    )
                st.session_state.incident_history.append(
                    {"role": "assistant", "content": ai_reply})
                st.session_state.incident_log.append(
                    f"[{now_vn().strftime('%H:%M')}] AI: {ai_reply[:100]}...")
                st.rerun()

        elif st.session_state.incident_log:
            # Hiển thị biên bản sau khi kết thúc
            log_text = "\n".join(st.session_state.incident_log)
            st.download_button(
                "📄 Tải biên bản sự cố (.txt)",
                data=f"BIÊN BẢN SỰ CỐ ATTP\n{'='*40}\n{log_text}",
                file_name=f"SuCo_ATTP_{now_vn().strftime('%d-%m-%Y_%H%M')}.txt",
                mime="text/plain", use_container_width=True,
            )
            with st.expander("Xem biên bản"):
                st.text(log_text)

        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown("**Hoặc dùng hướng dẫn tĩnh bên dưới:**")
    steps = [
        ("🛑", "Bước 1 — DỪNG BỮA ĂN NGAY",
         "Yêu cầu tất cả học sinh ngừng ăn. Không để thêm bất kỳ ai ăn thêm."),
        ("📞", "Bước 2 — GỌI CẤP CỨU 115 nếu cần",
         "Gọi **115** ngay nếu có học sinh: co giật, khó thở, mất ý thức, nôn ra máu."),
        ("🥣", "Bước 3 — GIỮ NGUYÊN MẪU THỨC ĂN",
         "**Không vứt, không rửa, không đổ** bất kỳ thức ăn nào. Đây là bằng chứng xét nghiệm nguyên nhân."),
        ("🔔", "Bước 4 — BÁO NGAY HIỆU TRƯỞNG & Y TẾ HỌC ĐƯỜNG",
         "Gọi điện trực tiếp (không nhắn tin). Cung cấp: số học sinh bị, triệu chứng, giờ ăn, tên món."),
        ("📝", "Bước 5 — GHI CHÉP ĐẦY ĐỦ",
         "Ghi ngay: số học sinh ảnh hưởng · triệu chứng cụ thể · thời gian bắt đầu · các món đã ăn · diễn biến theo thời gian."),
        ("🏥", "Bước 6 — BÁO SỞ Y TẾ trong 24 giờ",
         "Từ 2 người bị trở lên: bắt buộc báo Sở Y Tế địa phương trong 24h theo quy định TTLT 13/2016."),
    ]
    for icon, title, body in steps:
        st.markdown(f"""<div class="sf-card">
            <div class="sf-card-title">{icon} {title}</div>
            <div class="sf-card-body">{body}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">Số điện thoại quan trọng</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.markdown('<div class="metric-box"><div class="metric-lbl">Cấp Cứu</div><div class="metric-num c-red">115</div><div class="metric-lbl">Miễn phí · 24/7</div></div>', unsafe_allow_html=True)
    c2.markdown('<div class="metric-box"><div class="metric-lbl">Cục ATTP</div><div class="metric-num c-blue" style="font-size:1.4rem">1800 6838</div><div class="metric-lbl">Miễn phí · Giờ hành chính</div></div>', unsafe_allow_html=True)
    c3.markdown('<div class="metric-box"><div class="metric-lbl">Cảnh Sát</div><div class="metric-num c-orange">113</div><div class="metric-lbl">Khi có hành vi cố ý</div></div>', unsafe_allow_html=True)


# ── TAB 5: Về ứng dụng ───────────────────────────────────────────────────────
def tab_about():
    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">Về SchoolFood AI</div>
        <div class="sf-card-body">Nền tảng giám sát ATTP bữa ăn học đường — giúp mỗi bên thực hiện đúng vai trò, đúng thời điểm, có bằng chứng rõ ràng.</div>
    </div>""", unsafe_allow_html=True)

    for s in SCHEDULE:
        st.markdown(f"""<div class="sf-card" style="padding:14px 18px;border-left:3px solid {s['color']}">
            <div class="sf-card-title">{s['role']}</div>
            <div class="sf-card-body">{s['freq']} · {s['what']}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">Tài liệu pháp luật đã tải</div>', unsafe_allow_html=True)
    pdfs = sorted(LEGAL_DIR.glob("*.pdf"))
    for p in pdfs:
        st.success(f"✅ {p.name} ({p.stat().st_size // 1024} KB)")
    if not pdfs:
        st.warning("Chưa có file PDF trong 07_Legal_Regulations/")
    try:
        import pypdf  # noqa: F401
        st.success("✅ pypdf đã cài — AI đọc được nội dung văn bản pháp luật thực tế")
    except ImportError:
        st.warning("Chưa cài pypdf. Chạy: pip install pypdf")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="SchoolFood AI", page_icon="🍱",
                       layout="wide", initial_sidebar_state="expanded")
    inject_css()

    st.markdown("""<div class="sf-header">
        <h1>🍱 SchoolFood AI</h1>
        <p>Nền tảng giám sát An toàn Thực phẩm bữa ăn học đường · Phiên bản 1.1</p>
    </div>""", unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### ⚙️ Cài đặt")

        # ── Tự động đọc API key theo thứ tự ưu tiên ──────────────────────────
        # 1. Streamlit Cloud Secrets  (khi deploy — người dùng không cần nhập)
        # 2. Biến môi trường          (local .env)
        # 3. Nhập thủ công sidebar    (fallback cho developer)
        import os
        _secret_key = (
            st.secrets.get("ANTHROPIC_API_KEY", "")
            if hasattr(st, "secrets") else ""
        ) or os.environ.get("ANTHROPIC_API_KEY", "")

        if _secret_key:
            api_key = _secret_key
            st.markdown(
                '<div style="background:#F0FDF4;border:1px solid #86EFAC;'
                'border-radius:8px;padding:8px 12px;font-size:0.8rem;color:#166534">'
                '✅ <b>AI đã kết nối</b> — Hỏi đáp sẵn sàng</div>',
                unsafe_allow_html=True,
            )
        else:
            api_key = st.text_input(
                "Claude API Key",
                type="password",
                help="Lấy tại console.anthropic.com → API Keys",
                placeholder="sk-ant-api03-...",
            )
            if not api_key:
                st.caption("💡 Không có key? Tab Checklist vẫn dùng được đầy đủ.")
        st.markdown('<div class="sec-hdr">Hồ sơ người dùng</div>', unsafe_allow_html=True)
        role  = st.selectbox("Vai trò", ["Phụ Huynh", "Ban Giám Sát", "Y Tế Học Đường", "Ban Giám Hiệu"])
        level = st.selectbox("Cấp trường", ["Tiểu Học (6–11 tuổi)", "THCS (12–15 tuổi)", "THPT (16–18 tuổi)"])
        loc   = st.text_input("Tỉnh/Thành phố", value="TP. Hồ Chí Minh")
        DESCS = {
            "Phụ Huynh": "Xem thực đơn và kết quả kiểm tra, gửi phản hồi",
            "Ban Giám Sát": "Kiểm tra bếp ăn 2 lần/tuần, tạo báo cáo chính thức",
            "Y Tế Học Đường": "Ghi kiểm thực 3 bước hàng ngày, quản lý mẫu lưu",
            "Ban Giám Hiệu": "Xem tổng quan, duyệt báo cáo, quản lý nhà cung cấp",
        }
        st.info(f"**{role}:** {DESCS.get(role,'')}")
        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

        # ── Trạng thái nhắc nhở ──────────────────────────────────────────────
        st.markdown('<div class="sec-hdr">🔔 Nhắc nhở kiểm tra</div>',
                    unsafe_allow_html=True)
        now = now_vn()
        _t = _REMINDER_TIMES.get(role)
        if _t and now.weekday() < 5:
            insp_h, insp_m = _t["hour"], _t["min"]
            insp_total    = insp_h * 60 + insp_m
            current_total = now.hour * 60 + now.minute
            mins_left     = insp_total - current_total
            today_name    = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","CN"][now.weekday()]
            is_today      = now.weekday() in _t["days"]

            # Tính giờ nhắc nhở (15 phút trước) — tính ngoài f-string tránh lỗi
            remind_total = insp_total - 15
            remind_h     = remind_total // 60
            remind_m     = remind_total % 60
            remind_str   = f"{remind_h:02d}:{remind_m:02d}"
            insp_str     = f"{insp_h:02d}:{insp_m:02d}"

            if not is_today:
                next_day_idx = next(
                    (d for d in sorted(_t["days"]) if d > now.weekday()),
                    min(_t["days"])
                )
                next_name = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6"][next_day_idx]
                st.info(
                    f"Hôm nay ({today_name}) không có lịch kiểm tra.\n\n"
                    f"📅 Lịch tiếp theo: **{next_name} {insp_str}**\n\n"
                    f"Nhắc nhở sẽ hiện lúc **{remind_str}**"
                )
            elif 0 <= mins_left <= 15:
                st.success(f"🔔 **Đang nhắc nhở!** Còn {mins_left} phút đến {insp_str}")
            elif mins_left > 0:
                st.info(
                    f"⏰ Hôm nay ({today_name}) lúc **{insp_str}**\n\n"
                    f"Nhắc nhở sẽ hiện lúc **{remind_str}**\n\n"
                    f"Còn {mins_left} phút nữa."
                )
            else:
                st.warning(f"Đã qua giờ kiểm tra hôm nay ({insp_h:02d}:{insp_m:02d})")
            # Nút test
            if st.button("▶ Xem trước nhắc nhở", use_container_width=True):
                st.toast(f"⏰ Còn 15 phút đến giờ kiểm tra {insp_h:02d}:{insp_m:02d}!", icon="🔔")
        elif not _t:
            st.caption("Vai trò Phụ Huynh không có lịch kiểm tra cố định.")
        else:
            st.caption("Cuối tuần — không có bữa ăn bán trú.")

        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:0.78rem;color:#94A3B8;text-align:center'>"
            "🔴 Khẩn cấp: <b>115</b> · Cục ATTP: <b>1800 6838</b>"
            "</div>",
            unsafe_allow_html=True,
        )

    # Nhắc nhở kiểm tra nếu trong 15 phút trước giờ thực hiện
    show_reminder_banner(role)

    t1, t2, t3, t4, t5 = st.tabs([
        "💬 Hỏi đáp AI",
        "✅ Checklist kiểm tra",
        "📅 Lịch & thông báo",
        "🚨 Khẩn cấp",
        "ℹ️ Về ứng dụng",
    ])
    with t1: tab_chat(api_key, role, level, loc)
    with t2: tab_checklist(api_key)
    with t3: tab_schedule()
    with t4: tab_emergency(api_key)
    with t5: tab_about()


if __name__ == "__main__":
    main()
