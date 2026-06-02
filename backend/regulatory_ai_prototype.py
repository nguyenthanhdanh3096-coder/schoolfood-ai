#!/usr/bin/env python3
"""SchoolFood AI v2.1 — Phase 2B: Database (Supabase), History, Feedback Backend"""

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

# ── G1: Database Layer — Supabase ────────────────────────────────────────────
# Không dùng @cache_resource để tránh cache None từ trước khi có secrets
_sb_client = None
_sb_error  = ""

def _get_sb():
    """Kết nối Supabase — lazy init, không cache để đảm bảo luôn đọc secrets mới nhất."""
    global _sb_client, _sb_error

    # Đã kết nối rồi thì trả về luôn
    if _sb_client is not None:
        return _sb_client

    try:
        from supabase import create_client  # type: ignore

        # Thử đọc secrets theo nhiều cách
        url = ""
        key = ""
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_ANON_KEY"]
        except (KeyError, FileNotFoundError):
            try:
                url = st.secrets.get("SUPABASE_URL", "")
                key = st.secrets.get("SUPABASE_ANON_KEY", "")
            except Exception:
                pass

        if not url or not key:
            _sb_error = "SUPABASE_URL hoặc SUPABASE_ANON_KEY chưa được thêm vào Secrets"
            return None

        if not url.startswith("https://"):
            _sb_error = f"SUPABASE_URL không hợp lệ: {url[:30]}..."
            return None

        _sb_client = create_client(str(url), str(key))
        _sb_error  = ""
        return _sb_client

    except ImportError:
        _sb_error = "Package 'supabase' chưa được cài (kiểm tra requirements.txt)"
    except Exception as e:
        _sb_error = f"Lỗi kết nối: {str(e)[:100]}"

    return None

def db_ok() -> bool:
    """Kiểm tra database có sẵn sàng không."""
    return _get_sb() is not None

def db_error_msg() -> str:
    """Trả về thông báo lỗi kết nối (nếu có)."""
    return _sb_error

def db_save_checklist(school: str, date_str: str, inspector: str, menu: str,
                      level: str, results: dict, notes: dict,
                      alert_level: str, pass_count: int, fail_count: int,
                      ai_narrative: str = "",
                      extra_results: dict | None = None) -> str | None:
    """
    Lưu kết quả checklist Ban Giám Sát vào Supabase.
    Trả về session_id hoặc None nếu lỗi/không có DB.
    """
    sb = _get_sb()
    if not sb:
        return None
    try:
        sess = sb.table("checklist_sessions").insert({
            "school_name":    school or "Chưa nhập",
            "inspector_name": inspector or "",
            "check_date":     date_str,
            "menu_today":     menu or "",
            "school_level":   level,
            "check_type":     "ban_giam_sat",
            "alert_level":    alert_level,
            "total_items":    pass_count + fail_count,
            "pass_count":     pass_count,
            "fail_count":     fail_count,
            "ai_narrative":   ai_narrative[:2000] if ai_narrative else "",
        }).execute()
        if not sess.data:
            return None
        sid = sess.data[0]["id"]

        # Lưu từng điểm kiểm tra
        items = [
            {"session_id": sid, "item_code": k,
             "result": v.replace("✅ Đạt", "Đạt").replace("❌ Không Đạt", "Không Đạt"),
             "note": notes.get(k, ""),
             "is_critical": k in CRITICAL_ITEMS}
            for k, v in results.items() if v is not None
        ]
        if extra_results:
            items += [
                {"session_id": sid, "item_code": k,
                 "result": v.replace("✅ Đạt", "Đạt").replace("❌ Không Đạt", "Không Đạt"),
                 "note": "", "is_critical": False}
                for k, v in extra_results.items() if v is not None
            ]
        if items:
            sb.table("checklist_results").insert(items).execute()
        return sid
    except Exception as e:
        st.warning(f"⚠️ Không lưu được vào database: {e}", icon="💾")
        return None


def db_save_kiem_thuc(school: str, date_str: str, yte_name: str, menu: str,
                      all_results: dict, all_notes: dict, timestamps: dict,
                      pass_count: int, fail_count: int) -> str | None:
    """Lưu kết quả Kiểm thực 3 bước của Y Tế Học Đường."""
    sb = _get_sb()
    if not sb:
        return None
    try:
        sess = sb.table("checklist_sessions").insert({
            "school_name":    school or "Chưa nhập",
            "inspector_name": yte_name or "",
            "check_date":     date_str,
            "menu_today":     menu or "",
            "school_level":   "Y Tế Học Đường",
            "check_type":     "kiem_thuc_3_buoc",
            "alert_level":    "OK" if fail_count == 0 else "MAJOR",
            "total_items":    pass_count + fail_count,
            "pass_count":     pass_count,
            "fail_count":     fail_count,
        }).execute()
        if not sess.data:
            return None
        sid = sess.data[0]["id"]

        # Lưu từng điểm
        items = [
            {"session_id": sid, "item_code": k,
             "result": v.replace("✅ Đạt", "Đạt").replace("❌ Không Đạt", "Không Đạt"),
             "note": all_notes.get(k, ""),
             "is_critical": k in {"B3_05"}}
            for k, v in all_results.items() if v is not None
        ]
        if items:
            sb.table("checklist_results").insert(items).execute()

        # Lưu timestamp từng bước
        for step in KIEM_THUC:
            b = step["buoc"]
            ts = timestamps.get(b, "")
            step_results = {k: v for k, v in all_results.items()
                           if k.startswith(f"B{b}_")}
            sp = sum(1 for v in step_results.values() if v == "✅ Đạt")
            sf = sum(1 for v in step_results.values() if v == "❌ Không Đạt")
            # on_time: check if timestamp in window
            on_time = None
            if ts:
                try:
                    parts = step["time_window"].replace("–","-").split("-")
                    ws = sum(int(x)*m for x,m in zip(parts[0].strip().split(":"), [60,1]))
                    we = sum(int(x)*m for x,m in zip(parts[1].strip().split(":"), [60,1]))
                    tm = sum(int(x)*m for x,m in zip(ts.split(":")[:2], [60,1]))
                    on_time = ws <= tm <= we
                except Exception:
                    on_time = None
            sb.table("kiem_thuc_steps").insert({
                "session_id":  sid,
                "step_no":     b,
                "time_window": step["time_window"],
                "confirmed_at": ts,
                "on_time":     on_time,
                "pass_count":  sp,
                "fail_count":  sf,
            }).execute()
        return sid
    except Exception as e:
        st.warning(f"⚠️ Không lưu được vào database: {e}", icon="💾")
        return None


def db_save_feedback(school: str, category: str, content: str) -> bool:
    """Lưu feedback Phụ Huynh vào Supabase."""
    sb = _get_sb()
    if not sb:
        return False
    try:
        sb.table("parent_feedback").insert({
            "school_name": school or "Không rõ",
            "category":    category,
            "content":     content[:2000],
            "status":      "pending",
        }).execute()
        return True
    except Exception:
        return False


def db_get_sessions(school: str = "", limit: int = 30) -> list:
    """Lấy lịch sử phiên kiểm tra."""
    sb = _get_sb()
    if not sb:
        return []
    try:
        q = sb.table("checklist_sessions").select("*").order("created_at", desc=True).limit(limit)
        if school:
            q = q.eq("school_name", school)
        return q.execute().data or []
    except Exception:
        return []


def db_get_feedback(school: str = "", status: str = "pending") -> list:
    """Lấy feedback Phụ Huynh."""
    sb = _get_sb()
    if not sb:
        return []
    try:
        q = sb.table("parent_feedback").select("*").eq("status", status) \
            .order("created_at", desc=True).limit(50)
        if school:
            q = q.eq("school_name", school)
        return q.execute().data or []
    except Exception:
        return []


def db_update_feedback_status(feedback_id: str, new_status: str):
    """Ban Giám Hiệu đánh dấu feedback đã xử lý."""
    sb = _get_sb()
    if not sb:
        return
    try:
        sb.table("parent_feedback").update({
            "status": new_status,
            "reviewed_at": now_vn().isoformat(),
        }).eq("id", feedback_id).execute()
    except Exception:
        pass

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
# Model mặc định — Sonnet 4.6 cho tất cả text tasks
# Vision (ảnh): dùng Sonnet 4.6 (cũng hỗ trợ vision, rẻ hơn Opus ~5x)
MODEL         = "claude-sonnet-4-6"
MODEL_VISION  = "claude-sonnet-4-6"   # Thay vì opus — cùng chất lượng vision, tiết kiệm hơn
MAX_TOK       = 1200                   # Giảm từ 1500 — đủ cho hầu hết câu trả lời

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
            "👥 Ban Giám Sát (Đại Diện PHHS) — TRONG 5 PHÚT",
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
        "role": "👥 Ban Giám Sát (Đại Diện PHHS)",
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

# ── Kiểm thực 3 bước — dành riêng cho Y Tế Học Đường (TTLT 13/2016 Điều 9) ──
KIEM_THUC = [
    {
        "buoc": 1, "icon": "🥩",
        "label": "Bước 1 — TRƯỚC chế biến",
        "time_window": "8:00 – 9:30",
        "law": "TTLT 13/2016 Điều 9 – Khoản a",
        "desc": "Kiểm tra toàn bộ nguyên liệu đầu vào trước khi đưa vào sơ chế và chế biến",
        "color": "#2563EB",
        "items": [
            ("B1_01", "Thịt/cá có tem kiểm dịch thú y còn hiệu lực",
             "Xem tem trên bao bì hoặc trên thân con vật",
             "Có tem, còn hiệu lực, đúng ngày", "Không có tem hoặc tem đã hết hạn",
             "QCVN 8-1:2011/BYT"),
            ("B1_02", "Rau củ có hóa đơn nguồn gốc từ vựa có đăng ký",
             "Xem hóa đơn mua hàng trong ngày — phải có tên vựa, địa chỉ",
             "Hóa đơn hợp lệ, đúng ngày, có địa chỉ vựa rõ ràng", "Không có hóa đơn hoặc hóa đơn mờ",
             "NĐ 15/2018 Điều 11"),
            ("B1_03", "Tất cả nguyên liệu đóng gói còn hạn sử dụng ≥ 3 ngày",
             "Kiểm tra từng bao bì — ghi nhận loại nào hết hạn sớm nhất",
             "Tất cả còn ≥ 3 ngày so với hôm nay", "Bất kỳ loại nào hết hạn hoặc không có ngày",
             "Luật ATTP 55/2010 Điều 10"),
            ("B1_04", "Nhiệt độ tủ lạnh bảo quản thực phẩm sống < 5°C",
             "Đọc nhiệt kế gắn trên tủ hoặc đo bằng nhiệt kế thực phẩm",
             "< 5°C", "≥ 5°C — vùng nguy hiểm vi khuẩn tăng nhanh",
             "QCVN 8-1:2011/BYT + WHO Five Keys"),
            ("B1_05", "Thực phẩm sống và chín bảo quản tách biệt hoàn toàn",
             "Quan sát các ngăn tủ lạnh và khu vực sơ chế",
             "Riêng biệt rõ ràng, có nhãn phân loại", "Để chung — nguy cơ nhiễm chéo vi khuẩn",
             "NĐ 15/2018 Điều 12"),
        ]
    },
    {
        "buoc": 2, "icon": "🍳",
        "label": "Bước 2 — TRONG chế biến",
        "time_window": "9:30 – 10:30",
        "law": "TTLT 13/2016 Điều 9 – Khoản b",
        "desc": "Kiểm tra quá trình nấu ăn, vệ sinh nhân viên và an toàn trong bếp",
        "color": "#7C3AED",
        "items": [
            ("B2_01", "Thức ăn được nấu chín kỹ, nhiệt độ lõi ≥ 70°C",
             "Dùng nhiệt kế thực phẩm đo tại phần dày nhất",
             "≥ 70°C — vi khuẩn (Salmonella, E.coli) bị tiêu diệt", "< 70°C — chưa đủ chín kỹ",
             "WHO Five Keys to Safer Food — Key 4"),
            ("B2_02", "Nhân viên đeo khẩu trang, găng tay và tạp dề sạch",
             "Quan sát toàn bộ nhân viên trong bếp trong quá trình nấu",
             "100% nhân viên đeo đầy đủ và đúng cách", "Thiếu bảo hộ — nguy cơ lây nhiễm từ người",
             "NĐ 15/2018 Điều 13"),
            ("B2_03", "Dao và thớt riêng biệt cho thực phẩm sống và chín",
             "Kiểm tra màu sắc hoặc ký hiệu phân loại thớt/dao",
             "Có phân loại rõ ràng (màu hoặc ký hiệu S/C)", "Dùng chung — nhiễm chéo vi khuẩn",
             "HACCP nguyên tắc 2 + NĐ 15/2018"),
            ("B2_04", "Dụng cụ nấu ăn sạch sẽ, không rỉ sét, không nứt vỡ",
             "Quan sát nồi, chảo, muỗng, vá, rây... trước khi dùng",
             "Sạch, nguyên vẹn, không rỉ sét", "Rỉ sét hoặc nứt vỡ — trú ẩn vi khuẩn",
             "NĐ 15/2018 Điều 13"),
            ("B2_05", "Khu vực bếp sạch sẽ, không có côn trùng",
             "Quan sát mặt bếp, sàn, góc tường, ống thoát nước",
             "Sạch, không có ruồi/gián/kiến xuất hiện", "Bẩn hoặc có côn trùng — vector lây E.coli",
             "NĐ 15/2018 Điều 11"),
        ]
    },
    {
        "buoc": 3, "icon": "🍱",
        "label": "Bước 3 — SAU chế biến",
        "time_window": "10:30 – 11:00",
        "law": "TTLT 13/2016 Điều 9 – Khoản c",
        "desc": "Kiểm tra thức ăn trước khi phục vụ và lấy mẫu lưu nghiệm bắt buộc",
        "color": "#0D9488",
        "items": [
            ("B3_01", "Nhiệt độ thức ăn khi chia đúng chuẩn an toàn",
             "Đo nhiệt kế trực tiếp vào thức ăn tại thời điểm bắt đầu chia",
             "Nóng ≥ 60°C | Lạnh ≤ 5°C — an toàn hoàn toàn", "5°C < T < 60°C — vùng NGUY HIỂM",
             "QCVN 8-1:2011/BYT + HACCP CCP"),
            ("B3_02", "Thời gian từ khi nấu xong đến khi phục vụ < 2 giờ",
             "Ghi lại giờ nấu xong (từ bếp trưởng) và giờ bắt đầu chia",
             "Dưới 2 giờ — ngưỡng an toàn tuyệt đối", "Trên 4 giờ ở nhiệt độ phòng — nguy hiểm",
             "WHO Five Keys — Key 2"),
            ("B3_03", "Màu sắc và mùi vị thức ăn bình thường, không có dấu hiệu hỏng",
             "Quan sát màu từng món, ngửi mùi trực tiếp trước khi chia",
             "Màu tự nhiên đặc trưng, mùi thơm ngon", "Màu lạ, mùi chua/hôi/đắng bất thường",
             "QCVN 8-1:2011/BYT"),
            ("B3_04", "Khẩu phần ăn đủ theo định mức đã đăng ký với nhà trường",
             "Ước lượng hoặc cân thực tế một suất so với định mức đã ký hợp đồng",
             "Đạt ≥ 90% định mức đăng ký", "Thiếu >20% — vi phạm hợp đồng cung cấp",
             "QĐ 3958/QĐ-BYT 2025"),
            ("B3_05", "Đã lấy mẫu lưu nghiệm 24h từng món — nhãn đầy đủ",
             "Kiểm tra tủ lạnh lưu mẫu: mỗi món ≥ 100g, nhãn ghi tên món + giờ lấy + ngày",
             "Có mẫu đủ lượng từng món, nhãn đầy đủ 3 thông tin", "Không có mẫu lưu hoặc thiếu nhãn",
             "TTLT 13/2016 Điều 9 — BẮT BUỘC PHÁP LUẬT"),
        ]
    },
]

# ── G4: Checklist Nhà Cung Cấp (12 điểm) ────────────────────────────────────
SUPPLIER_ITEMS = [
    {"code": "S01", "icon": "📄", "critical": True,
     "desc": "Giấy phép CSSX/KDDV thực phẩm còn hiệu lực",
     "hint": "Kiểm tra số giấy phép, ngày cấp, ngày hết hạn trên văn bản gốc",
     "pass_std": "Còn hiệu lực, đúng địa chỉ cơ sở", "fail_std": "Hết hạn hoặc không xuất trình được",
     "law": "Luật ATTP 55/2010 Điều 34"},
    {"code": "S02", "icon": "🏅", "critical": True,
     "desc": "Giấy chứng nhận cơ sở đủ điều kiện ATTP còn hiệu lực",
     "hint": "Chứng nhận 3 năm/lần cấp bởi Sở Y Tế hoặc Sở NN&PTNT",
     "pass_std": "Còn hiệu lực, không quá 3 năm kể từ ngày cấp", "fail_std": "Hết hạn hoặc không có",
     "law": "NĐ 15/2018 Điều 11"},
    {"code": "S03", "icon": "🚚", "critical": True,
     "desc": "Xe/thùng vận chuyển cách nhiệt, sạch sẽ, không côn trùng",
     "hint": "Quan sát trực tiếp xe hoặc thùng lạnh khi giao hàng",
     "pass_std": "Kín, sạch, không mùi hôi, không côn trùng", "fail_std": "Bẩn, nứt vỡ hoặc có côn trùng",
     "law": "NĐ 15/2018 Điều 18"},
    {"code": "S04", "icon": "🌡️", "critical": True,
     "desc": "Nhiệt độ vận chuyển thực phẩm chín ≥ 60°C hoặc lạnh < 8°C",
     "hint": "Dùng nhiệt kế đo tại điểm trung tâm thùng hàng khi nhận",
     "pass_std": "Nóng ≥ 60°C | Lạnh < 8°C", "fail_std": "8°C–60°C — vùng nguy hiểm vi khuẩn",
     "law": "QCVN 8-1:2011/BYT + WHO Five Keys"},
    {"code": "S05", "icon": "🧾", "critical": True,
     "desc": "Hóa đơn và chứng từ nguồn gốc thực phẩm cho lô hàng hôm nay",
     "hint": "Hóa đơn phải ghi đúng ngày, tên hàng, đơn vị cung cấp có địa chỉ rõ ràng",
     "pass_std": "Hóa đơn đủ hàng, đúng ngày, có địa chỉ nhà cung cấp",
     "fail_std": "Không có hóa đơn hoặc hóa đơn viết tay mờ",
     "law": "NĐ 15/2018 Điều 11"},
    {"code": "S06", "icon": "🏷️", "critical": False,
     "desc": "Nhãn mác thực phẩm đóng gói đủ: ngày sản xuất, hạn dùng, nơi sản xuất",
     "hint": "Kiểm tra mẫu ngẫu nhiên 3 gói/thùng hàng",
     "pass_std": "Đủ 3 thông tin bắt buộc, chữ rõ, không tẩy xóa",
     "fail_std": "Thiếu 1 trong 3 thông tin hoặc nhãn bị che/xóa",
     "law": "NĐ 43/2017/NĐ-CP về nhãn hàng hóa"},
    {"code": "S07", "icon": "📋", "critical": False,
     "desc": "Thực đơn giao khớp với đơn đặt hàng và cam kết dinh dưỡng",
     "hint": "So sánh phiếu giao hàng hôm nay với thực đơn tuần đã ký duyệt",
     "pass_std": "Khớp hoàn toàn hoặc sai lệch < 5% có báo trước",
     "fail_std": "Thiếu món hoặc thay thế không báo trước",
     "law": "QĐ 3958/QĐ-BYT 2025"},
    {"code": "S08", "icon": "⚖️", "critical": False,
     "desc": "Khẩu phần đủ định lượng: thịt/cá ≥ định mức ký hợp đồng",
     "hint": "Cân ngẫu nhiên 3 suất ăn, so với định mức đã ký",
     "pass_std": "Đạt ≥ 90% định mức", "fail_std": "Thiếu > 10% định mức",
     "law": "QĐ 3958/QĐ-BYT 2025 + hợp đồng cung cấp"},
    {"code": "S09", "icon": "👷", "critical": False,
     "desc": "Nhân viên giao hàng đeo khẩu trang, găng tay, đồng phục sạch",
     "hint": "Quan sát tất cả người tiếp xúc trực tiếp với thực phẩm",
     "pass_std": "100% nhân viên đeo đầy đủ BHLĐ", "fail_std": "Bất kỳ ai thiếu BHLĐ",
     "law": "NĐ 15/2018 Điều 13"},
    {"code": "S10", "icon": "📦", "critical": False,
     "desc": "Dụng cụ đựng thực phẩm kín, sạch, không nứt vỡ",
     "hint": "Kiểm tra khay, hộp, nồi đựng khi giao",
     "pass_std": "Kín, sạch, nguyên vẹn", "fail_std": "Nứt vỡ hoặc bẩn",
     "law": "NĐ 15/2018 Điều 13"},
    {"code": "S11", "icon": "🧫", "critical": True,
     "desc": "Mẫu lưu thực phẩm được giao đúng quy định (≥ 3 mẫu, ≥ 100g/mẫu, nhãn đủ 3 thông tin)",
     "hint": "Kiểm tra tủ lạnh mẫu lưu: tên món + giờ lấy + ngày",
     "pass_std": "Đủ số lượng, đủ trọng lượng, nhãn đầy đủ",
     "fail_std": "Thiếu mẫu, thiếu lượng hoặc thiếu nhãn",
     "law": "TTLT 13/2016 Điều 9 — BẮT BUỘC PHÁP LUẬT"},
    {"code": "S12", "icon": "⏰", "critical": False,
     "desc": "Thời gian giao hàng đúng lịch (trước bữa ăn tối thiểu 30 phút)",
     "hint": "Ghi lại giờ xe đến cổng trường vs giờ bắt đầu phục vụ",
     "pass_std": "Đến đúng giờ hoặc sớm hơn ≥ 30 phút",
     "fail_std": "Trễ > 15 phút so với lịch hẹn",
     "law": "Điều khoản hợp đồng cung cấp"},
]
SUPPLIER_CRITICAL = {"S01", "S02", "S03", "S04", "S05", "S11"}
SUPPLIER_SCORE_PASS = 10   # ≥ 10/12 + critical OK → Loại A
SUPPLIER_SCORE_WARN = 8    # 8–9/12 → Loại B

# ── CSS ────────────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Xoá hoàn toàn khoảng trắng trên cùng */
    #MainMenu, footer, header { display: none !important; }
    [data-testid="stHeader"]  { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    .main .block-container {
        padding-top: 0.6rem !important;
        padding-bottom: 1.5rem !important;
        max-width: 1200px !important;
    }

    .stApp { background-color: #F0F4F8; }

    /* Ẩn hoàn toàn nút đóng sidebar — người dùng không thể đóng sidebar trên desktop */
    @media (min-width: 769px) {
        [data-testid="stSidebarCollapseButton"],
        button[title="Close sidebar"],
        button[aria-label="Close sidebar"],
        [data-testid="stSidebar"] > div:first-child > div > button,
        section[data-testid="stSidebar"] > div > div > div > button { display: none !important; }
    }
    /* Nút MỞ LẠI (nếu vẫn lỡ đóng trên mobile) — đỏ nổi bật */
    [data-testid="collapsedControl"],
    button[title="Open sidebar"],
    button[aria-label="Open sidebar"] {
        background: #DC2626 !important; border-radius: 0 14px 14px 0 !important;
        display: flex !important; visibility: visible !important;
        align-items: center !important; justify-content: center !important;
        width: 44px !important; min-height: 100px !important;
        opacity: 1 !important; z-index: 999999 !important;
        position: fixed !important; left: 0 !important; top: calc(50% - 50px) !important;
        box-shadow: 4px 0 20px rgba(220,38,38,0.5) !important;
        cursor: pointer !important; border: none !important;
    }
    [data-testid="collapsedControl"] svg,
    button[title="Open sidebar"] svg { fill: white !important; color: white !important; }

    /* sf-header không còn dùng — đã thay bằng HTML inline trong main() */
    .sf-header { display: none; }

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

    /* Input disabled — override màu xám mặc định, giữ chữ đọc được */
    input:disabled, input[disabled] {
        -webkit-text-fill-color: #16A34A !important;
        color: #16A34A !important;
        opacity: 1 !important;
        font-weight: 600 !important;
        background-color: #F0FDF4 !important;
        border-color: #86EFAC !important;
        cursor: default !important;
    }

    /* ── Ẩn nút đóng sidebar trên desktop (phòng người dùng vô tình đóng) ── */
    @media (min-width: 769px) {
        [data-testid="stSidebarCollapseButton"],
        button[title="Close sidebar"],
        button[aria-label="Close sidebar"],
        [data-testid="stSidebar"] > div:first-child > div > button {
            display: none !important;
        }
    }

    /* ── Nút MỞ LẠI sidebar khi lỡ đóng — đỏ nổi bật, không thể bỏ qua ── */
    [data-testid="collapsedControl"],
    button[title="Open sidebar"],
    button[aria-label="Open sidebar"] {
        background: #DC2626 !important;
        border-radius: 0 14px 14px 0 !important;
        display: flex !important;
        visibility: visible !important;
        align-items: center !important;
        justify-content: center !important;
        width: 44px !important;
        min-height: 100px !important;
        opacity: 1 !important;
        z-index: 999999 !important;
        position: fixed !important;
        left: 0 !important;
        top: calc(50% - 50px) !important;
        box-shadow: 4px 0 16px rgba(220,38,38,0.4) !important;
        cursor: pointer !important;
        border: none !important;
        transition: width 0.2s ease !important;
    }
    [data-testid="collapsedControl"]::after,
    button[title="Open sidebar"]::after,
    button[aria-label="Open sidebar"]::after {
        content: "☰" !important;
        color: white !important;
        font-size: 1.3rem !important;
        font-weight: bold !important;
    }
    [data-testid="collapsedControl"] svg,
    button[title="Open sidebar"] svg,
    button[aria-label="Open sidebar"] svg {
        fill: white !important;
        color: white !important;
        opacity: 1 !important;
    }
    [data-testid="collapsedControl"]:hover,
    button[title="Open sidebar"]:hover,
    button[aria-label="Open sidebar"]:hover {
        background: #B91C1C !important;
        width: 52px !important;
    }

    /* ── Mobile responsive ── */
    @media (max-width: 768px) {
        /* ── FIX MOBILE KEYBOARD: iOS tự zoom khi font < 16px → mất khoảng cách ── */
        input[type="text"],
        input[type="search"],
        input[type="email"],
        input[type="password"],
        input[type="number"],
        textarea,
        select {
            font-size: 16px !important;          /* Ngăn iOS Safari auto-zoom */
            -webkit-text-size-adjust: 100% !important;
        }
        /* Streamlit specific inputs */
        .stTextInput input,
        .stTextArea textarea,
        .stSelectbox select,
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea {
            font-size: 16px !important;
            touch-action: manipulation !important; /* Ngăn double-tap delay */
        }

        /* Header mới (inline HTML) — thu nhỏ trên mobile */
        .main .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }

        /* Card padding giảm */
        .sf-card { padding: 14px 14px !important; }

        /* Metric boxes nhỏ hơn, font nhỏ hơn */
        .metric-box { min-height: 80px !important; padding: 10px 8px !important; }
        .metric-num { font-size: 1.5rem !important; }
        .metric-lbl { font-size: 0.7rem !important; }

        /* Nút bấm full width trên mobile */
        .stButton > button { min-height: 44px !important; font-size: 0.85rem !important; }

        /* Columns stack dọc trên mobile */
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
        }
        [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }

        /* Segmented control mobile */
        [data-baseweb="button-group"] {
            flex-direction: row !important;
            gap: 3px !important;
        }
        [data-baseweb="button-group"] button {
            font-size: 0.72rem !important;
            padding: 5px 6px !important;
        }

        /* Tab labels ngắn hơn */
        .stTabs [data-baseweb="tab"] {
            font-size: 0.75rem !important;
            padding: 8px 8px !important;
        }

        /* Alert boxes padding */
        .alert-critical, .alert-major, .alert-minor, .alert-ok {
            padding: 12px 14px !important;
        }

        /* Group title font nhỏ hơn */
        .group-title { font-size: 0.72rem !important; }

        /* Schedule cards */
        .schedule-card { padding: 12px 14px !important; }
    }

    @media (max-width: 480px) {
        .metric-num { font-size: 1.2rem !important; }
    }

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
        return "❌ API Key không hợp lệ. Kiểm tra lại ở thanh cài đặt phía trên."
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
    "Ban Giám Sát (Đại Diện PHHS)": {
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

    unanswered = sorted(c for c, v in results.items() if v is None)
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
            model=MODEL_VISION,
            max_tokens=500,   # JSON output ngắn gọn, không cần nhiều
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
            model=MODEL,
            max_tokens=800,   # JSON array 3-5 items, giảm từ 1200
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
            model=MODEL,
            max_tokens=400,   # Đoạn văn 120-160 từ, giảm từ 500
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

    left_cells = ["Đại diện Ban Giám Sát (Đại Diện PHHS)", "", "", ""]
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
            model=MODEL,
            max_tokens=500,   # Giảm từ 600 — hướng dẫn từng bước ngắn gọn
            system=[{"type": "text", "text": INCIDENT_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],  # Cache system prompt
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
        "Ban Giám Sát (Đại Diện PHHS)": [
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
            st.warning("⚠️ Vui lòng nhập API Key ở thanh cài đặt phía trên.")
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
                            placeholder="VD: Cơm, thịt kho trứng, rau muống xào tỏi, canh chua cá",
                            key="shared_menu")

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

    if "cl_r"       not in st.session_state: st.session_state.cl_r       = {}
    if "cl_n"       not in st.session_state: st.session_state.cl_n       = {}
    if "cl_photos"  not in st.session_state: st.session_state.cl_photos  = {}
    if "cl_extra"   not in st.session_state: st.session_state.cl_extra   = []
    if "photo_analysis" not in st.session_state: st.session_state.photo_analysis = {}

    # ── Giải thích cấu trúc checklist ────────────────────────────────────────
    st.markdown(f"""
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                padding:12px 16px;margin-bottom:12px;font-size:0.85rem">
        <b>📋 Cấu trúc kiểm tra:</b>
        <span style="color:#1E293B">
          &nbsp;&nbsp;🔵 <b>20 câu chuẩn</b> — luôn có, không cần API
          &nbsp;&nbsp;|&nbsp;&nbsp;
          🤖 <b>Câu hỏi AI bổ sung</b> — tùy chọn, theo thực đơn hôm nay
          {"&nbsp;&nbsp;|&nbsp;&nbsp;<span style='color:#2563EB'>💳 Mỗi lần tạo ≈ $0.004 credit</span>" if ai_on else ""}
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ── AI #1: Tạo checklist bổ sung theo thực đơn ───────────────────────────
    if ai_on and menu:
        col_btn, col_status = st.columns([0.5, 0.5])
        if col_btn.button("🤖 Tạo câu hỏi bổ sung theo thực đơn (~$0.004)",
                          use_container_width=True, key="gen_extra"):
            with st.spinner("AI đang phân tích thực đơn và tra cứu QCVN..."):
                extras = generate_extra_checklist(menu, level_key, api_key)
                st.session_state.cl_extra = extras
                st.session_state.photo_analysis = {}
        if st.session_state.cl_extra:
            col_status.markdown(
                f'<span style="color:#16A34A;font-size:0.85rem">✅ Đã tạo '
                f'<b>{len(st.session_state.cl_extra)}</b> câu hỏi — '
                f'<span style="color:#94A3B8">căn cứ QCVN + NĐ 15/2018</span></span>',
                unsafe_allow_html=True,
            )
    elif ai_on and not menu:
        st.caption("💡 Nhập thực đơn hôm nay bên trên để AI tạo câu hỏi kiểm tra riêng.")
    else:
        st.caption("🔌 Kết nối API key ở thanh cài đặt phía trên để dùng tính năng tạo câu hỏi theo thực đơn.")

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    cl = get_checklist(level_key)

    # ── FIX: Pre-initialize TRƯỚC KHI render để tránh reset state khi rerun ──
    # Đồng bộ cl_r từ widget state — nguồn sự thật là session_state[seg_{code}]
    # Không pre-init "Chưa chấm" → segmented_control bắt đầu với None (chưa chọn)
    for _, grp_items in cl:
        for item_code, *_ in grp_items:
            st.session_state.cl_r[item_code] = st.session_state.get(f"seg_{item_code}")

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
            # Đọc TRỰC TIẾP từ widget key → không lag, chuyển màu ngay lần bấm đầu tiên
            cur_state = st.session_state.get(f"seg_{code}")
            if cur_state == "✅ Đạt":
                row_left = "#16A34A"; row_bg = "#F0FDF4"
                code_clr = "#166534"; code_icon = "✅"
                state_label = '<span style="font-size:0.7rem;font-weight:700;color:#16A34A;margin-left:6px">ĐẠT</span>'
            elif cur_state == "❌ Không Đạt":
                row_left = "#DC2626"; row_bg = "#FFF5F5"
                code_clr = "#991B1B"; code_icon = "❌"
                state_label = '<span style="font-size:0.7rem;font-weight:700;color:#DC2626;margin-left:6px">KHÔNG ĐẠT</span>'
            else:  # None — chưa chọn
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
                st.segmented_control(
                    label=code,
                    options=["✅ Đạt", "❌ Không Đạt"],
                    key=f"seg_{code}",
                    label_visibility="collapsed",
                )
                result = st.session_state.get(f"seg_{code}")  # None nếu chưa chọn
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
        with st.expander(
            f"📷 Ảnh minh chứng — {group_name}"
            + (" · 🤖 AI phân tích ảnh (~$0.015/ảnh)" if ai_on else "")
        ):
            # Hướng dẫn chụp ảnh đạt chuẩn
            st.markdown("""
            <div style="background:#FFFBEB;border:1px solid #FCD34D;border-radius:8px;
                        padding:10px 14px;margin-bottom:10px;font-size:0.8rem;color:#78350F">
                <b>📐 Chụp ảnh để AI phân tích chính xác:</b><br>
                ✅ Đủ sáng, không ngược sáng &nbsp;|&nbsp;
                ✅ Cách 20–50cm, chụp thẳng &nbsp;|&nbsp;
                ✅ Ảnh nét, không bị mờ &nbsp;|&nbsp;
                ✅ Chụp rõ vùng cần kiểm tra<br>
                ❌ Tránh: tối, mờ nhòe, góc nghiêng >45°, che khuất vùng cần xem<br>
                <span style="color:#92400E"><b>Lưu ý:</b> Claude Vision phân tích dấu hiệu
                <b>nhìn thấy bằng mắt</b> — không thể phát hiện vi khuẩn vô hình
                hay đo nhiệt độ thực tế.</span>
            </div>
            """, unsafe_allow_html=True)

            photo_col1, photo_col2 = st.columns(2)
            with photo_col1:
                st.caption("📱 Chụp ảnh (camera điện thoại/webcam)")
                cam = st.camera_input("Chụp ảnh", key=f"cam_{g_idx}",
                                      label_visibility="collapsed")
                if cam:
                    st.session_state.cl_photos[f"cam_{g_idx}"] = cam
                    st.success("✅ Đã lưu ảnh chụp")
            with photo_col2:
                st.caption("💻 Tải ảnh từ thư viện máy (tối đa 3 ảnh/mục)")
                upl = st.file_uploader(
                    "Tải ảnh", type=["jpg", "jpeg", "png", "heic"],
                    key=f"upl_{g_idx}", label_visibility="collapsed",
                    accept_multiple_files=True,
                )
                if upl:
                    if len(upl) > 3:
                        st.warning("⚠️ Chỉ lưu 3 ảnh đầu tiên (giới hạn 3 ảnh/mục)")
                        upl = upl[:3]
                    st.session_state.cl_photos[f"upl_{g_idx}"] = upl
                    st.success(f"✅ Đã tải {len(upl)}/3 ảnh")

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
    answered_count = sum(1 for v in st.session_state.cl_r.values() if v is not None)
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
            seg_key = f"seg_extra_{code}"
            # Đọc trực tiếp từ widget key để màu cập nhật ngay
            _ex_cur = st.session_state.get(seg_key)
            if _ex_cur == "✅ Đạt":
                _ex_left, _ex_bg, _ex_icon = "#16A34A", "#F0FDF4", "✅"
                _ex_lbl = '<span style="font-size:0.7rem;font-weight:700;color:#16A34A;margin-left:6px">ĐẠT</span>'
            elif _ex_cur == "❌ Không Đạt":
                _ex_left, _ex_bg, _ex_icon = "#DC2626", "#FFF5F5", "❌"
                _ex_lbl = '<span style="font-size:0.7rem;font-weight:700;color:#DC2626;margin-left:6px">KHÔNG ĐẠT</span>'
            else:
                _ex_left, _ex_bg, _ex_icon = "#2563EB", "#EFF6FF", "🤖"
                _ex_lbl = '<span style="font-size:0.7rem;color:#2563EB;margin-left:6px">chưa chấm</span>'
            col_d, col_c = st.columns([0.65, 0.35])
            with col_d:
                st.markdown(
                    f'<div style="background:{_ex_bg};border-left:3px solid {_ex_left};'
                    f'border-radius:0 8px 8px 0;padding:8px 14px;margin:3px 0">'
                    f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'
                    f'<span style="font-size:0.7rem;font-weight:800;color:{_ex_left}">{_ex_icon} {code}</span>'
                    f'<span style="font-size:0.72rem;color:#1D4ED8;background:#DBEAFE;'
                    f'padding:1px 6px;border-radius:8px">{ingr}</span>'
                    f'{_ex_lbl}</div>'
                    f'<div style="font-size:0.88rem;font-weight:500;color:#1E293B">{desc}</div>'
                    + (f'<div style="font-size:0.75rem;color:#64748B;margin-top:2px">{why}</div>' if why else '')
                    + '</div>', unsafe_allow_html=True,
                )
                with st.expander("Hướng dẫn"):
                    st.markdown(
                        f"**Kiểm tra:** {item.get('how','')}  \n"
                        f"**✅ Đạt:** {item.get('pass','')}  \n"
                        f"**❌ Không đạt:** {item.get('fail','')}"
                    )
            with col_c:
                st.segmented_control(
                    code, ["✅ Đạt", "❌ Không Đạt"],
                    key=seg_key, label_visibility="collapsed",
                )
                st.session_state.cl_extra_r[code] = st.session_state.get(seg_key)
        if st.button("🗑️ Xoá câu hỏi AI", use_container_width=True):
            st.session_state.cl_extra = []
            st.rerun()

    # ── Nút tạo báo cáo ──────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)

    # Guard chống duplicate save: mỗi tổ hợp (trường + ngày + người kt) chỉ lưu 1 lần
    _save_guard_key = f"cl_saved_{school}_{date}_{insp}"
    _already_saved  = st.session_state.get(_save_guard_key, False)

    if st.button(
        "📄 Tạo báo cáo kiểm tra" if can_submit else "⛔ Hoàn thành đủ 20 mục để xuất báo cáo",
        type="primary" if can_submit else "secondary",
        disabled=not can_submit,
        use_container_width=True,
    ):
        alert_key = determine_alert(st.session_state.cl_r, cl)
        date_vn   = date.strftime("%d/%m/%Y")
        date_iso  = date.strftime("%Y-%m-%d")
        report    = _build_report(school, date_vn, insp, menu, level_key,
                                  st.session_state.cl_r, st.session_state.cl_n,
                                  pass_count, fail_count, alert_key, cl)
        photo_count = sum(
            (len(v) if isinstance(v, list) else 1)
            for v in st.session_state.cl_photos.values() if v
        )

        # ── G1: Auto-save vào Supabase ────────────────────────────────────────
        # ── AI #3: Tóm tắt ngôn ngữ tự nhiên ────────────────────────────────
        narrative = ""
        if ai_on:
            with st.spinner("🤖 AI đang viết tóm tắt báo cáo..."):
                narrative = generate_ai_narrative(
                    st.session_state.cl_r, st.session_state.cl_n,
                    alert_key, school, date_vn, menu,
                    pass_count, pass_count + fail_count, level_key, api_key,
                )
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

        # ── G1: Auto-save vào Supabase (guard chống duplicate) ───────────────
        if not _already_saved:
            extra_r    = st.session_state.get("cl_extra_r", {})
            session_id = db_save_checklist(
                school, date_iso, insp, menu, level_key,
                st.session_state.cl_r, st.session_state.cl_n,
                alert_key, pass_count, fail_count,
                ai_narrative=narrative,
                extra_results=extra_r or None,
            )
            if session_id:
                st.session_state[_save_guard_key] = True   # Đánh dấu đã lưu
                st.success(f"💾 Đã lưu vào database (ID: `{session_id[:8]}...`)")
            elif db_ok():
                st.warning("⚠️ Lưu database thất bại — báo cáo vẫn tải được bình thường")
        else:
            st.info("💾 Báo cáo này đã được lưu trước đó.")

        # ── Tải báo cáo Word (.docx) ─────────────────────────────────────────
        with st.spinner("⚙️ Đang tạo file Word..."):
            docx_bytes = generate_word_report(
                school, date_vn, insp, menu, level_key,
                st.session_state.cl_r, st.session_state.cl_n,
                pass_count, fail_count, alert_key, cl,
                narrative,
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
# ── Tab riêng cho Phụ Huynh (chỉ xem, không thực hiện checklist) ─────────────
def tab_parent_view(api_key: str = ""):
    """View dành cho Phụ Huynh — xem thực đơn, kết quả kiểm tra, gửi phản hồi."""
    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">👨‍👩‍👧 Góc Phụ Huynh</div>
        <div class="sf-card-body">
            Phụ Huynh có quyền xem thực đơn, đọc kết quả kiểm tra của Ban Giám Sát
            và gửi phản hồi về bữa ăn. Việc thực hiện checklist thuộc thẩm quyền của
            <b>Ban Giám Sát (Đại Diện PHHS)</b> được bầu chính thức.
        </div>
    </div>""", unsafe_allow_html=True)

    # Phần 1 — Thực đơn hôm nay (đọc từ session_state nếu Y Tế đã nhập)
    st.markdown('<div class="sec-hdr">📋 Thực đơn hôm nay</div>', unsafe_allow_html=True)
    menu_today = st.session_state.get("shared_menu", "").strip()
    if menu_today:
        st.markdown(
            f'<div class="sf-card" style="border-left:4px solid #16A34A">'
            f'<div style="font-size:0.78rem;color:#16A34A;font-weight:700;margin-bottom:4px">'
            f'✅ Thực đơn đã được cập nhật</div>'
            f'<div style="font-size:0.95rem;color:#1E293B;font-weight:500">{menu_today}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="sf-card" style="border-left:4px solid #2563EB">'
            '<div class="sf-card-body">Thực đơn chưa được cập nhật. '
            'Y Tế Học Đường sẽ nhập thực đơn trước bữa ăn vào tab ✅ Checklist kiểm tra. '
            'Hoặc xem bảng thực đơn treo tại cổng trường.</div></div>',
            unsafe_allow_html=True,
        )

    # Phần 2 — Kết quả kiểm tra mới nhất
    st.markdown('<div class="sec-hdr">✅ Kết quả kiểm tra gần nhất</div>',
                unsafe_allow_html=True)
    if st.session_state.get("cl_r"):
        pass_ct = sum(1 for v in st.session_state.cl_r.values() if v == "✅ Đạt")
        fail_ct = sum(1 for v in st.session_state.cl_r.values() if v == "❌ Không Đạt")
        total   = pass_ct + fail_ct
        if total > 0:
            pct = int(pass_ct / total * 100)
            from datetime import date
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"""<div class="metric-box">
                <div class="metric-lbl">Điểm đạt</div>
                <div class="metric-num c-green">{pass_ct}</div>
                <div class="metric-lbl">/ {total} đã chấm</div>
            </div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="metric-box">
                <div class="metric-lbl">Tỷ lệ</div>
                <div class="metric-num {'c-green' if pct>=90 else 'c-orange' if pct>=75 else 'c-red'}">{pct}%</div>
                <div class="metric-lbl">đạt chuẩn</div>
            </div>""", unsafe_allow_html=True)
            c3.markdown(f"""<div class="metric-box">
                <div class="metric-lbl">Điểm không đạt</div>
                <div class="metric-num c-red">{fail_ct}</div>
                <div class="metric-lbl">điểm</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.info("Ban Giám Sát chưa thực hiện checklist trong phiên này.")
    else:
        st.info("Chưa có kết quả kiểm tra. Ban Giám Sát thực hiện kiểm tra 2 lần/tuần.")

    # Phần 3 — Quyền của Phụ Huynh
    st.markdown('<div class="sec-hdr">⚖️ Quyền của Phụ Huynh theo pháp luật</div>',
                unsafe_allow_html=True)
    rights = [
        ("Xem thực đơn",
         "Nhà trường phải công khai thực đơn — yêu cầu Y Tế Học Đường hoặc xem bảng thông báo."),
        ("Yêu cầu Ban Đại Diện PHHS giám sát",
         "Phụ Huynh có quyền đề nghị Ban Đại Diện PHHS kiểm tra đột xuất bếp ăn."),
        ("Phản ánh chất lượng",
         "Gửi phản hồi qua form bên dưới hoặc liên hệ trực tiếp Hiệu Trưởng."),
        ("Tiếp cận kết quả kiểm tra",
         "Báo cáo kiểm tra ATTP là tài liệu có thể được chia sẻ với phụ huynh khi yêu cầu."),
    ]
    for title, desc in rights:
        st.markdown(f"""<div class="sf-card" style="padding:12px 16px;margin:6px 0">
            <span style="font-weight:600;color:#1E293B;font-size:0.88rem">{title}</span>
            <div style="font-size:0.83rem;color:#475569;margin-top:3px">{desc}</div>
        </div>""", unsafe_allow_html=True)

    # Phần 4 — Gửi phản hồi (không dùng div wrapper — gây thanh trắng rỗng)
    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">📤 Gửi phản hồi về bữa ăn</div>',
                unsafe_allow_html=True)
    loai = st.selectbox("Loại phản hồi", [
        "Chọn loại phản hồi...",
        "Chất lượng thức ăn (khẩu phần, hương vị)",
        "Vệ sinh (nghi ngờ không sạch)",
        "Ngộ độc hoặc dấu hiệu bất thường",
        "Thiếu dinh dưỡng theo chuẩn",
        "Thực đơn không như đã thông báo",
        "Khác",
    ])
    noi_dung = st.text_area(
        "Mô tả cụ thể (ngày, bữa ăn, triệu chứng nếu có...)",
        height=120,
        placeholder="Ví dụ: Hôm nay 01/06, con tôi kể thức ăn có mùi lạ ở bữa trưa...",
    )

    if st.button("📤 Gửi phản hồi", type="primary", use_container_width=True):
        if loai == "Chọn loại phản hồi..." or not noi_dung.strip():
            st.warning("⚠️ Vui lòng chọn loại phản hồi và điền nội dung trước khi gửi.")
        elif "Ngộ độc" in loai:
            st.error(
                "🚨 Nếu nghi ngờ ngộ độc: gọi ngay **115** và chuyển sang tab **🚨 Khẩn cấp** "
                "để biết quy trình xử lý đúng."
            )
        else:
            # G2: Lưu feedback vào Supabase
            school_name = st.session_state.get("kt_school", "") or "Chưa nhập"
            saved = db_save_feedback(school_name, loai, noi_dung)
            if saved:
                st.success(
                    "✅ Đã ghi nhận phản hồi và lưu vào hệ thống. "
                    "Ban Giám Hiệu sẽ xem xét và phản hồi trong 1–2 ngày làm việc."
                )
            else:
                st.success(
                    "✅ Đã ghi nhận phản hồi. "
                    "*(Lưu ý: chưa kết nối database — phản hồi chưa được lưu vĩnh viễn)*"
                )

    # Hỏi đáp AI (nếu có)
    if api_key:
        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sec-hdr">💬 Hỏi AI về quyền Phụ Huynh</div>',
                    unsafe_allow_html=True)
        st.caption("Đặt câu hỏi tự do về ATTP, quyền phụ huynh, xử lý khi nghi ngờ ngộ độc...")
        q = st.text_input("Câu hỏi của bạn", placeholder="VD: Con tôi đau bụng sau bữa trưa, tôi cần làm gì?")
        if q:
            from anthropic import Anthropic
            with st.spinner("AI đang trả lời..."):
                sys = build_system_prompt("Phụ Huynh", "tiểu học", "Việt Nam")
                ans = ask_claude(Anthropic(api_key=api_key), sys, [], q)
                st.info(ans)


# ── Kiểm thực 3 bước — Tab dành riêng Y Tế Học Đường ────────────────────────
def tab_kiem_thuc(api_key: str = "", level: str = "Tiểu Học (6–11 tuổi)"):
    """Kiểm thực 3 bước theo TTLT 13/2016 — dành riêng cho Y Tế Học Đường."""
    ai_on = bool(api_key)
    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">🏥 Kiểm thực 3 bước — Y Tế Học Đường</div>
        <div class="sf-card-body">
            Căn cứ: <b>TTLT 13/2016/TTLT-BYT-BGDĐT Điều 9</b> — Thực hiện hàng ngày, song song
            với sổ kiểm thực giấy bắt buộc. Mỗi bước ghi nhận <b>timestamp tự động</b>.
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Banner tiêu chuẩn dinh dưỡng — dùng level từ thanh điều khiển ───────
    n_yte = NUTRITION.get(level, NUTRITION[list(NUTRITION.keys())[0]])
    st.markdown(
        f'<div class="nutrition-banner">'
        f'<div class="nutrition-label">📊 Tiêu Chuẩn Dinh Dưỡng Bữa Trưa — Cấp {n_yte["short"]} (QĐ 3958/QĐ-BYT 2025)</div>'
        f'<div class="nutrition-grid">'
        f'<div class="nutrition-item">⚡ Năng lượng: <span class="nutrition-val">{n_yte["kcal"]}</span> ({n_yte["pct_day"]} nhu cầu ngày)</div>'
        f'<div class="nutrition-item">🥩 Thịt/cá tối thiểu: <span class="nutrition-val">{n_yte["meat_g"]}g/học sinh</span></div>'
        f'<div class="nutrition-item">🥦 Rau xanh: <span class="nutrition-val">{n_yte["veg_range"]}/học sinh</span></div>'
        f'<div class="nutrition-item">💪 Protein: <span class="nutrition-val">{n_yte["protein_pct"]}</span> tổng năng lượng</div>'
        f'</div>'
        f'<div style="font-size:0.75rem;color:#1D4ED8;margin-top:6px">💡 {n_yte["note"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Thông tin buổi kiểm tra
    st.markdown('<div class="sec-hdr">Thông tin ca kiểm thực</div>', unsafe_allow_html=True)
    kc1, kc2, kc3, kc4 = st.columns(4)
    kt_school = kc1.text_input("Tên trường", placeholder="TH Nguyễn Du, Q.1",
                                key="kt_school")
    kt_date   = kc2.date_input("Ngày", value=datetime.today(), format="DD/MM/YYYY",
                                key="kt_date")
    kt_name   = kc3.text_input("Y Tế Học Đường", placeholder="Họ và tên",
                                key="kt_name")
    kt_menu   = kc4.text_input("Thực đơn hôm nay",
                                placeholder="Cơm, thịt kho, rau...",
                                key="kt_menu_yte")

    # ── AI: Tạo câu hỏi bổ sung theo thực đơn ───────────────────────────────
    if "kt_extra" not in st.session_state: st.session_state.kt_extra = []
    if "kt_photo_analysis" not in st.session_state: st.session_state.kt_photo_analysis = {}

    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;'
        f'padding:10px 16px;margin-bottom:10px;font-size:0.82rem">'
        f'📋 <b>15 câu kiểm thực chuẩn</b> (luôn có) &nbsp;|&nbsp; '
        f'{"🤖 <b>AI bổ sung</b> theo thực đơn (~$0.004) &nbsp;|&nbsp; 📷 <b>AI phân tích ảnh</b> (~$0.015/ảnh)" if ai_on else "<i style=color:#94A3B8>Kết nối API key để dùng AI phân tích ảnh và tạo câu hỏi theo thực đơn</i>"}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if ai_on and kt_menu:
        cb1, cb2 = st.columns([0.5, 0.5])
        if cb1.button("🤖 Tạo câu hỏi bổ sung theo thực đơn (~$0.004)",
                      use_container_width=True, key="kt_gen_extra"):
            with st.spinner("AI đang phân tích thực đơn..."):
                extras = generate_extra_checklist(kt_menu, "Y Tế Học Đường", api_key)
                st.session_state.kt_extra = extras
        if st.session_state.kt_extra:
            cb2.markdown(
                f'<span style="color:#16A34A;font-size:0.85rem;line-height:3">'
                f'✅ Đã tạo {len(st.session_state.kt_extra)} câu bổ sung</span>',
                unsafe_allow_html=True,
            )
    elif ai_on and not kt_menu:
        st.caption("💡 Nhập thực đơn để AI tạo câu hỏi kiểm tra riêng theo nguyên liệu hôm nay.")

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

    # Khởi tạo session state cho 3 bước
    for b in [1, 2, 3]:
        if f"kt_b{b}_r" not in st.session_state: st.session_state[f"kt_b{b}_r"] = {}
        if f"kt_b{b}_n" not in st.session_state: st.session_state[f"kt_b{b}_n"] = {}
        if f"kt_b{b}_done" not in st.session_state: st.session_state[f"kt_b{b}_done"] = None
        if f"kt_b{b}_photos" not in st.session_state: st.session_state[f"kt_b{b}_photos"] = {}
        # Không pre-init kt_seg_* → segmented_control bắt đầu None (chưa chọn)

    # ── Render từng bước ──────────────────────────────────────────────────────
    for step in KIEM_THUC:
        b      = step["buoc"]
        clr    = step["color"]
        done_t = st.session_state.get(f"kt_b{b}_done")

        # Header bước
        status_badge = (
            f'<span style="background:#DCFCE7;color:#166534;font-size:0.75rem;'
            f'font-weight:700;padding:2px 10px;border-radius:12px;margin-left:8px">'
            f'✅ Hoàn thành lúc {done_t}</span>' if done_t else
            f'<span style="background:#FEF9C3;color:#92400E;font-size:0.75rem;'
            f'font-weight:700;padding:2px 10px;border-radius:12px;margin-left:8px">'
            f'⏳ Chưa hoàn thành</span>'
        )
        st.markdown(
            f'<div style="display:flex;align-items:center;padding:12px 0 4px 0;'
            f'border-bottom:2px solid {clr}">'
            f'<span style="font-size:1.5rem;margin-right:10px">{step["icon"]}</span>'
            f'<div><div style="font-size:1rem;font-weight:700;color:{clr}">'
            f'{step["label"]}</div>'
            f'<div style="font-size:0.78rem;color:#64748B">'
            f'⏰ {step["time_window"]} &nbsp;·&nbsp; {step["law"]}</div></div>'
            f'{status_badge}</div>',
            unsafe_allow_html=True,
        )
        st.caption(step["desc"])

        # 5 câu hỏi của bước này
        for (code, desc, how, pass_cond, fail_cond, legal) in step["items"]:
            # Đọc trực tiếp từ widget key → màu đổi ngay lần bấm đầu tiên
            cur = st.session_state.get(f"kt_seg_{code}")
            if cur == "✅ Đạt":
                row_bg, row_left = "#F0FDF4", "#16A34A"
                code_clr, code_icon, lbl = "#166534", "✅", "ĐẠT"
            elif cur == "❌ Không Đạt":
                row_bg, row_left = "#FFF5F5", "#DC2626"
                code_clr, code_icon, lbl = "#991B1B", "❌", "KHÔNG ĐẠT"
            else:  # None — chưa chọn
                row_bg, row_left = "#FFFBEB", "#F59E0B"
                code_clr, code_icon, lbl = "#D97706", "○", "chưa kiểm tra"

            col_d, col_c = st.columns([0.62, 0.38])
            with col_d:
                is_critical_item = code == "B3_05"  # Mẫu lưu là bắt buộc pháp lý
                crit_badge = (
                    '<span style="background:#FEE2E2;color:#991B1B;font-size:0.65rem;'
                    'font-weight:700;padding:1px 6px;border-radius:8px;margin-left:4px;'
                    'border:1px solid #FECACA">BẮT BUỘC PHÁP LUẬT</span>'
                    if is_critical_item else ""
                )
                st.markdown(
                    f'<div style="background:{row_bg};border-left:3px solid {row_left};'
                    f'border-radius:0 8px 8px 0;padding:10px 14px;margin:3px 0">'
                    f'<span style="font-size:0.7rem;font-weight:800;color:{code_clr}">'
                    f'{code_icon} {code}</span>'
                    f'<span style="font-size:0.68rem;color:#64748B;margin-left:6px">{legal}</span>'
                    f'{crit_badge}'
                    f'<div style="font-size:0.875rem;font-weight:500;color:#1E293B;margin-top:3px">'
                    f'{desc}</div></div>',
                    unsafe_allow_html=True,
                )
                with st.expander("🔍 Hướng dẫn"):
                    st.markdown(
                        f"**Thực hiện:** {how}  \n"
                        f"**✅ Đạt khi:** {pass_cond}  \n"
                        f"**❌ Không đạt khi:** {fail_cond}"
                    )
            with col_c:
                st.segmented_control(
                    code, ["✅ Đạt", "❌ Không Đạt"],
                    key=f"kt_seg_{code}", label_visibility="collapsed",
                )
                st.session_state[f"kt_b{b}_r"][code] = \
                    st.session_state.get(f"kt_seg_{code}")
                note = st.text_input(
                    f"ghi chú {code}", label_visibility="collapsed",
                    placeholder="Ghi chú...", key=f"kt_note_{code}",
                )
                st.session_state[f"kt_b{b}_n"][code] = note

        # ── Ảnh minh chứng + AI Vision ───────────────────────────────────────
        exp_label = (
            f"📷 Ảnh minh chứng Bước {b} (tối đa 4 ảnh/bước)"
            + (" · 🤖 AI phân tích (~$0.015/ảnh)" if ai_on else "")
        )
        with st.expander(exp_label):
            st.caption("📐 Ảnh nét, đủ sáng, chụp thẳng cách 20–50cm. Camera: 1 ảnh · Tải lên: tối đa 3 ảnh")
            pc1, pc2 = st.columns(2)
            with pc1:
                st.caption("📱 Chụp ảnh (1 ảnh)")
                cam = st.camera_input("Chụp ảnh", key=f"kt_cam_{b}",
                                      label_visibility="collapsed")
                if cam:
                    st.session_state[f"kt_b{b}_photos"]["cam"] = cam
                    st.success("✅ Đã lưu ảnh chụp")
            with pc2:
                st.caption("💻 Tải ảnh từ máy (tối đa 3 ảnh)")
                upl = st.file_uploader("Tải ảnh", type=["jpg","jpeg","png","heic"],
                                       key=f"kt_upl_{b}", label_visibility="collapsed",
                                       accept_multiple_files=True)
                if upl:
                    if len(upl) > 3:
                        st.warning("⚠️ Chỉ lưu 3 ảnh đầu tiên")
                        upl = upl[:3]
                    st.session_state[f"kt_b{b}_photos"]["upl"] = upl
                    st.success(f"✅ Đã tải {len(upl)}/3 ảnh")

            # ── AI Vision phân tích ảnh ───────────────────────────────────
            active_photo = (
                st.session_state[f"kt_b{b}_photos"].get("cam") or
                (st.session_state[f"kt_b{b}_photos"].get("upl") or [None])[0]
            )
            if ai_on and active_photo:
                if st.button(f"🔍 Phân tích ảnh Bước {b} với AI",
                             key=f"kt_analyze_{b}", use_container_width=True):
                    with st.spinner("AI đang phân tích ảnh..."):
                        photo_bytes = (active_photo.read()
                                       if hasattr(active_photo, "read")
                                       else active_photo.getvalue())
                        result = analyze_photo_ai(photo_bytes, step["label"], api_key)
                        st.session_state.kt_photo_analysis[b] = result

                if b in st.session_state.kt_photo_analysis:
                    r = st.session_state.kt_photo_analysis[b]
                    lvl  = r.get("risk_level", "OK")
                    clr  = {"OK":"#16A34A","WARNING":"#D97706","CRITICAL":"#DC2626"}.get(lvl,"#64748B")
                    bg   = {"OK":"#F0FDF4","WARNING":"#FFFBEB","CRITICAL":"#FEF2F2"}.get(lvl,"#F8FAFC")
                    icon = {"OK":"✅","WARNING":"⚠️","CRITICAL":"🚨"}.get(lvl,"❓")
                    conf = int(r.get("confidence",0.8)*100)
                    issues_html = "".join(f"<li style='color:#DC2626'>{i}</li>" for i in r.get("issues",[]))
                    pos_html    = "".join(f"<li style='color:#16A34A'>{p}</li>" for p in r.get("positives",[]))
                    st.markdown(
                        f'<div style="background:{bg};border-left:4px solid {clr};'
                        f'border-radius:8px;padding:10px 14px;margin-top:8px">'
                        f'<div style="font-weight:700;color:{clr};margin-bottom:4px">'
                        f'{icon} {lvl} — Độ tin cậy: {conf}%</div>'
                        f'{"<ul style=margin:2px 0;padding-left:14px>"+issues_html+"</ul>" if issues_html else ""}'
                        f'{"<ul style=margin:2px 0;padding-left:14px>"+pos_html+"</ul>" if pos_html else ""}'
                        f'{"<div style=font-size:0.8rem;color:#475569;margin-top:4px><b>Khuyến nghị:</b> "+r.get("recommendation","")+"</div>" if r.get("recommendation") else ""}'
                        f'</div>', unsafe_allow_html=True
                    )
            elif not ai_on and active_photo:
                st.caption("💡 Kết nối API key để AI phân tích ảnh tự động.")

        # Nút xác nhận hoàn thành bước
        b_results = st.session_state.get(f"kt_b{b}_r", {})
        b_answered = sum(1 for v in b_results.values() if v is not None)
        b_total    = len(step["items"])
        b_fail     = sum(1 for v in b_results.values() if v == "❌ Không Đạt")

        col_btn, col_prog = st.columns([0.4, 0.6])
        with col_btn:
            can_confirm = (b_answered == b_total)

            if done_t:
                # ── Đã xác nhận — hiển thị trạng thái hoàn thành rõ ràng ──
                st.markdown(
                    f'<div style="background:#DCFCE7;border:2px solid #16A34A;'
                    f'border-radius:10px;padding:12px 16px;text-align:center">'
                    f'<div style="font-weight:700;color:#166534;font-size:0.95rem">'
                    f'✅ Bước {b} đã hoàn thành</div>'
                    f'<div style="color:#16A34A;font-size:0.85rem;margin-top:4px">'
                    f'🕐 Xác nhận lúc <b>{done_t}</b> '
                    f'({["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","CN"][now_vn().weekday()]})'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
                # Nút bỏ xác nhận (nếu cần chỉnh lại)
                if st.button(f"↩ Bỏ xác nhận Bước {b}", key=f"kt_undo_{b}",
                             use_container_width=True):
                    st.session_state[f"kt_b{b}_done"] = None
                    st.rerun()

            elif can_confirm:
                # ── Đủ điều kiện xác nhận ──
                if st.button(
                    f"☑ Xác nhận hoàn thành Bước {b}",
                    key=f"kt_confirm_{b}",
                    type="primary",
                    use_container_width=True,
                ):
                    ts = now_vn().strftime("%H:%M:%S")  # Lưu giờ:phút:giây
                    st.session_state[f"kt_b{b}_done"] = ts
                    st.toast(f"✅ Bước {b} xác nhận lúc {ts}", icon="🕐")
                    st.rerun()
            else:
                # ── Chưa đủ điều kiện ──
                st.markdown(
                    f'<div style="background:#F8FAFC;border:1px dashed #CBD5E1;'
                    f'border-radius:10px;padding:12px 16px;text-align:center;color:#94A3B8;'
                    f'font-size:0.85rem">'
                    f'⏳ Còn <b>{b_total - b_answered}</b> câu chưa kiểm tra</div>',
                    unsafe_allow_html=True,
                )

        with col_prog:
            pct = int(b_answered / b_total * 100) if b_total else 0
            fail_note = f" — ⚠️ {b_fail} không đạt" if b_fail else ""
            bar_color = "#16A34A" if pct == 100 else "#2563EB"
            st.markdown(
                f'<div style="margin-top:8px">'
                f'<div style="font-size:0.78rem;color:#64748B;margin-bottom:3px">'
                f'{b_answered}/{b_total} câu đã kiểm tra{fail_note}</div>'
                f'<div style="background:#E2E8F0;border-radius:20px;height:8px">'
                f'<div style="width:{pct}%;background:{bar_color};'
                f'border-radius:20px;height:100%;transition:width 0.4s ease"></div></div>'
                f'{"<div style=font-size:0.75rem;color:#16A34A;margin-top:4px>✅ Tất cả câu đã kiểm tra</div>" if pct==100 else ""}'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

    # ── Câu hỏi AI bổ sung (nếu có) ──────────────────────────────────────────
    if st.session_state.kt_extra:
        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="sec-hdr">🤖 Câu hỏi bổ sung AI ({len(st.session_state.kt_extra)} câu) — theo thực đơn hôm nay</div>',
            unsafe_allow_html=True,
        )
        if "kt_extra_r" not in st.session_state: st.session_state.kt_extra_r = {}
        for item in st.session_state.kt_extra:
            code = item.get("code","?"); desc = item.get("desc","")
            ingr = item.get("ingredient",""); legal_ref = item.get("legal_ref","")
            col_d, col_c = st.columns([0.65, 0.35])
            with col_d:
                st.markdown(
                    f'<div style="background:#EFF6FF;border-left:3px solid #2563EB;'
                    f'border-radius:0 8px 8px 0;padding:8px 14px;margin:3px 0">'
                    f'<span style="font-size:0.7rem;font-weight:800;color:#2563EB">🤖 {code}</span>'
                    f'<span style="font-size:0.72rem;color:#1D4ED8;margin-left:6px;'
                    f'background:#DBEAFE;padding:1px 6px;border-radius:8px">{ingr}</span>'
                    f'<div style="font-size:0.86rem;font-weight:500;color:#1E293B;margin-top:3px">{desc}</div>'
                    f'{"<div style=font-size:0.72rem;color:#64748B;margin-top:2px>"+legal_ref+"</div>" if legal_ref else ""}'
                    f'</div>', unsafe_allow_html=True,
                )
                if item.get("how") or item.get("pass"):
                    with st.expander("Hướng dẫn"):
                        st.markdown(
                            f"**Kiểm tra:** {item.get('how','')}  \n"
                            f"**✅ Đạt:** {item.get('pass','')}  \n"
                            f"**❌ Không đạt:** {item.get('fail','')}"
                        )
            with col_c:
                seg_key = f"kt_seg_extra_{code}"
                st.segmented_control(
                    code, ["✅ Đạt", "❌ Không Đạt"],
                    key=seg_key, label_visibility="collapsed",
                )
                st.session_state.kt_extra_r[code] = st.session_state.get(seg_key)
        if st.button("🗑️ Xoá câu hỏi AI", use_container_width=True, key="kt_del_extra"):
            st.session_state.kt_extra = []; st.rerun()

    # ── Tổng kết 3 bước ───────────────────────────────────────────────────────
    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">Tổng kết ca kiểm thực</div>', unsafe_allow_html=True)

    all_results = {}
    for b in [1, 2, 3]:
        all_results.update(st.session_state.get(f"kt_b{b}_r", {}))
    total_items  = sum(len(s["items"]) for s in KIEM_THUC)
    total_done   = sum(1 for v in all_results.values() if v is not None)
    total_pass   = sum(1 for v in all_results.values() if v == "✅ Đạt")
    total_fail   = sum(1 for v in all_results.values() if v == "❌ Không Đạt")
    steps_done   = sum(1 for b in [1, 2, 3]
                       if st.session_state.get(f"kt_b{b}_done"))

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">Bước hoàn thành</div>
        <div class="metric-num {'c-green' if steps_done==3 else 'c-orange'}">{steps_done}/3</div>
    </div>""", unsafe_allow_html=True)
    m2.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">✅ Đạt chuẩn</div>
        <div class="metric-num c-green">{total_pass}</div>
        <div class="metric-lbl">/ {total_items} điểm</div>
    </div>""", unsafe_allow_html=True)
    m3.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">❌ Không đạt</div>
        <div class="metric-num c-red">{total_fail}</div>
        <div class="metric-lbl">điểm</div>
    </div>""", unsafe_allow_html=True)
    m4.markdown(f"""<div class="metric-box">
        <div class="metric-lbl">Mẫu lưu B3_05</div>
        <div class="metric-num {'c-green' if all_results.get('B3_05')=='✅ Đạt' else 'c-red'}">
            {'✅' if all_results.get('B3_05')=='✅ Đạt' else '❌'}
        </div>
        <div class="metric-lbl">{'Đã lưu' if all_results.get('B3_05')=='✅ Đạt' else 'Chưa lưu!'}</div>
    </div>""", unsafe_allow_html=True)

    # ── Nút xuất sổ kiểm thực ────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    all_notes = {}
    for b in [1, 2, 3]:
        all_notes.update(st.session_state.get(f"kt_b{b}_n", {}))

    # Timestamps từng bước để đưa vào báo cáo
    timestamps = {
        b: st.session_state.get(f"kt_b{b}_done") or ""
        for b in [1, 2, 3]
    }

    # Điều kiện xuất: PHẢI hoàn thành ĐỦ cả 3 bước VÀ đủ 15 câu
    all_steps_confirmed = all(timestamps[b] for b in [1, 2, 3])
    all_items_answered  = (total_done == total_items)
    can_export = all_steps_confirmed and all_items_answered

    # Hiển thị checklist điều kiện xuất
    cond_rows = [
        (all_items_answered, f"Đã kiểm tra đủ 15/15 câu hỏi ({total_done}/{total_items})"),
        (bool(timestamps[1]),
         f"Bước 1 đã xác nhận{' lúc ' + timestamps[1] if timestamps[1] else ' — chưa xác nhận'}"),
        (bool(timestamps[2]),
         f"Bước 2 đã xác nhận{' lúc ' + timestamps[2] if timestamps[2] else ' — chưa xác nhận'}"),
        (bool(timestamps[3]),
         f"Bước 3 đã xác nhận{' lúc ' + timestamps[3] if timestamps[3] else ' — chưa xác nhận'}"),
    ]
    cond_html = "".join(
        f'<div style="font-size:0.82rem;padding:3px 0;color:{"#16A34A" if ok else "#DC2626"}">'
        f'{"✅" if ok else "❌"} {label}</div>'
        for ok, label in cond_rows
    )
    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;'
        f'padding:14px 18px;margin-bottom:12px">'
        f'<div style="font-size:0.8rem;font-weight:700;color:#334155;margin-bottom:6px">'
        f'Điều kiện để xuất sổ kiểm thực:</div>'
        f'{cond_html}</div>',
        unsafe_allow_html=True,
    )

    if can_export:
        # G1: Auto-save kiểm thực — guard chống duplicate
        date_vn_kt    = kt_date.strftime("%d/%m/%Y")
        date_iso_kt   = kt_date.strftime("%Y-%m-%d")
        _kt_guard_key = f"kt_saved_{kt_school}_{date_vn_kt}_{kt_name}"
        if not st.session_state.get(_kt_guard_key, False):
            sid_kt = db_save_kiem_thuc(
                kt_school, date_iso_kt, kt_name, kt_menu,
                all_results, all_notes, timestamps,
                total_pass, total_fail,
            )
            if sid_kt:
                st.session_state[_kt_guard_key] = True
                st.success(f"💾 Đã lưu vào database (ID: `{sid_kt[:8]}...`)")
        else:
            st.info("💾 Sổ kiểm thực này đã được lưu trước đó.")

        with st.spinner("Đang tạo sổ kiểm thực..."):
            docx_bytes = generate_so_kiem_thuc_docx(
                kt_school, date_vn_kt,
                kt_name, kt_menu, all_results, all_notes, timestamps,
            )
        fname = f"SoKiemThuc_{(kt_school or 'Truong').replace(' ','_')}_{kt_date.strftime('%d-%m-%Y')}.docx"
        st.download_button(
            "📋 Xuất Sổ Kiểm Thực (.docx) — chuẩn TTLT 13/2016",
            data=docx_bytes, file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, type="primary",
        )
    else:
        missing = sum(1 for ok, _ in cond_rows if not ok)
        st.button(
            f"⛔ Chưa đủ điều kiện xuất — còn {missing} điều kiện chưa đáp ứng",
            disabled=True, use_container_width=True,
        )


def generate_so_kiem_thuc_docx(school: str, date_str: str, yte_name: str,
                                menu: str, results: dict, notes: dict,
                                timestamps: dict | None = None) -> bytes:
    """Tạo Sổ Kiểm Thực 3 Bước chuẩn TTLT 13/2016 — Times New Roman.
    timestamps: {1: "HH:MM:SS", 2: "HH:MM:SS", 3: "HH:MM:SS"} để xác minh timeline.
    """
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from io import BytesIO

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(3.0); sec.right_margin = Cm(2.0)

    # Quốc hiệu
    _docx_para(doc, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
               bold=True, size=13, align="center", space_after=2)
    _docx_para(doc, "Độc lập – Tự do – Hạnh phúc",
               bold=True, size=12, align="center", space_after=2)
    _docx_para(doc, "────────────────────────────",
               size=10, align="center", space_after=4)
    _docx_para(doc, f"TP. Hồ Chí Minh, ngày {date_str}",
               size=12, align="right", space_after=10)

    _docx_para(doc, "SỔ KIỂM THỰC 3 BƯỚC",
               bold=True, size=15, align="center", space_after=2)
    _docx_para(doc, "BỮA ĂN HỌC ĐƯỜNG",
               bold=True, size=13, align="center", space_after=2)
    _docx_para(doc,
               "(Căn cứ: TTLT số 13/2016/TTLT-BYT-BGDĐT ngày 12/5/2016 – Điều 9)",
               size=11, align="center", space_after=10)

    # Thông tin chung
    info_rows = [
        ("Cơ sở giáo dục", school or "..."),
        ("Ngày kiểm thực", date_str),
        ("Nhân viên y tế thực hiện", yte_name or "..."),
        ("Thực đơn bữa ăn", menu or "..."),
    ]
    t = doc.add_table(rows=len(info_rows), cols=2)
    t.style = "Table Grid"
    for i, (k, v) in enumerate(info_rows):
        r0 = t.rows[i].cells[0].paragraphs[0].add_run(k)
        r1 = t.rows[i].cells[1].paragraphs[0].add_run(v)
        _docx_set_font(r0, bold=True, size_pt=11)
        _docx_set_font(r1, size_pt=11)
        t.rows[i].cells[0].width = Cm(6)
    doc.add_paragraph()

    # Chi tiết từng bước — bao gồm timestamp xác nhận để xác minh timeline
    ts_map = timestamps or {}
    for step in KIEM_THUC:
        b_num = step["buoc"]
        ts    = ts_map.get(b_num, "")
        # Xác minh timeline — kiểm tra ĐẦY ĐỦ khung giờ (start <= ts <= end)
        def _parse_hhmm(t: str) -> int:
            """Chuyển 'HH:MM' hoặc 'HH:MM:SS' thành tổng phút."""
            parts = t.strip().split(":")
            return int(parts[0]) * 60 + int(parts[1]) if len(parts) >= 2 else -1

        # Phân tích "8:00 – 9:30" → start=480 phút, end=570 phút
        w_parts = step["time_window"].replace("–", "-").replace("—", "-").split("-")
        w_start = _parse_hhmm(w_parts[0]) if len(w_parts) >= 1 else 0
        w_end   = _parse_hhmm(w_parts[1]) if len(w_parts) >= 2 else 1439

        ts_mins  = _parse_hhmm(ts) if ts else -1
        on_time  = (w_start <= ts_mins <= w_end) if ts_mins >= 0 else None

        ts_label = (
            f" ✅ Xác nhận lúc {ts} — đúng khung giờ ({step['time_window']})"
            if on_time is True else
            f" ⚠️ NGOÀI KHUNG GIỜ: Xác nhận lúc {ts} (yêu cầu: {step['time_window']})"
            if on_time is False else
            " ❌ Chưa xác nhận"
        )

        _docx_para(doc,
                   f"{step['icon']}  {step['label']}  ({step['time_window']})  —  {step['law']}",
                   bold=True, size=13, space_before=8, space_after=2)

        # Dòng thời gian — highlight đỏ nếu ngoài khung giờ
        p_ts = doc.add_paragraph()
        p_ts.paragraph_format.space_after = Pt(4)
        r_ts = p_ts.add_run(f"⏱ Thời gian thực hiện:{ts_label}")
        _docx_set_font(r_ts, bold=(on_time is False), size_pt=11,
                       color=(192, 0, 0) if on_time is False else
                       (22, 163, 74) if on_time is True else (100, 116, 139))

        _docx_para(doc, step["desc"], size=11, space_after=4)

        tbl = doc.add_table(rows=1 + len(step["items"]), cols=4)
        tbl.style = "Table Grid"
        _docx_table_header(tbl, ["Mã", "Nội dung kiểm tra", "Kết quả", "Ghi chú"])
        widths = [Cm(1.5), Cm(8.5), Cm(2.5), Cm(4.5)]
        for i, (code, desc, *_) in enumerate(step["items"]):
            row  = tbl.rows[i + 1]
            res  = results.get(code, "Chưa kiểm tra")
            note = notes.get(code, "")
            status = res.replace("✅ Đạt", "ĐẠT").replace("❌ Không Đạt", "KHÔNG ĐẠT").replace("Chưa kiểm tra", "—")
            cells_data = [code, desc, status, note]
            for j, (cell, val, w) in enumerate(zip(row.cells, cells_data, widths)):
                cell.width = w
                r = cell.paragraphs[0].add_run(val)
                is_fail = status == "KHÔNG ĐẠT" and j == 2
                _docx_set_font(r, bold=is_fail, size_pt=10,
                               color=(192, 0, 0) if is_fail else None)
        doc.add_paragraph()

    # Chữ ký
    _docx_para(doc, f"Ngày kiểm thực: {date_str}   |   Giờ hoàn thành: ___:___",
               size=11, space_before=10, space_after=10)
    sig = doc.add_table(rows=3, cols=2)
    for i, (l, r_) in enumerate([
        ("Xác nhận Hiệu Trưởng", "Nhân viên Y Tế Học Đường"),
        ("(ký, đóng dấu)", "(ký và ghi rõ họ tên)"),
        ("", yte_name or ""),
    ]):
        for cell, txt in [(sig.rows[i].cells[0], l), (sig.rows[i].cells[1], r_)]:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = cell.paragraphs[0].add_run(txt)
            _docx_set_font(r, bold=(i == 0), size_pt=12)

    _docx_para(doc, "─" * 50, size=9, align="center", space_before=14, space_after=2)
    _docx_para(doc,
               "Sổ kiểm thực này được tạo bằng SchoolFood AI v2.0 — "
               f"song song với sổ giấy bắt buộc theo TTLT 13/2016 Điều 9",
               size=9, align="center")

    buf = BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


# ── Nội dung sổ tay — dùng chung cho tab_guide() và generate_user_manual_docx()
MANUAL_CONTENT = {
    "title": "SỔ TAY HƯỚNG DẪN SỬ DỤNG SCHOOLFOOD AI",
    "subtitle": "Nền tảng giám sát An toàn Thực phẩm bữa ăn học đường",
    "version": "v2.0 — Tháng 6/2026",
    "sections": [
        {
            "id": "intro",
            "icon": "🍱",
            "title": "1. SchoolFood AI là gì?",
            "content": (
                "SchoolFood AI là nền tảng công nghệ giúp các bên liên quan tại trường học "
                "giám sát An toàn Thực phẩm (ATTP) bữa ăn bán trú một cách hệ thống, có căn "
                "cứ pháp luật và dễ thực hiện.\n\n"
                "App KHÔNG thay thế xét nghiệm vi sinh học trong phòng thí nghiệm. "
                "App hỗ trợ kiểm tra cảm quan, ghi nhận hồ sơ và cảnh báo sớm các "
                "dấu hiệu rủi ro nhìn thấy bằng mắt thường."
            ),
            "subsections": [
                ("Vấn đề đang giải quyết",
                 "Mỗi ngày hơn 1 triệu học sinh Hà Nội và hàng triệu học sinh cả nước ăn "
                 "bán trú tại trường. Phụ huynh lo lắng nhưng không có công cụ giám sát; "
                 "Ban Giám sát muốn kiểm tra nhưng không biết kiểm tra gì đúng chuẩn; "
                 "Y tế học đường ghi sổ giấy rồi cất vào tủ. SchoolFood AI lấp đầy khoảng trống này."),
                ("Ai nên dùng app này",
                 "• Phụ Huynh — xem thực đơn, kết quả kiểm tra, phản hồi\n"
                 "• Ban Giám Sát (Đại Diện PHHS) — thực hiện checklist 20 điểm và tạo báo cáo\n"
                 "• Y Tế Học Đường — số hoá kiểm thực 3 bước hàng ngày\n"
                 "• Ban Giám Hiệu — xem tổng quan và duyệt báo cáo"),
            ]
        },
        {
            "id": "roles",
            "icon": "👥",
            "title": "2. Hướng dẫn theo vai trò",
            "subsections": [
                ("👨‍👩‍👧 Phụ Huynh — làm gì trong app",
                 "1. Chọn vai trò 'Phụ Huynh' ở sidebar\n"
                 "2. Tab 💬 Hỏi đáp AI: đặt câu hỏi bằng tiếng Việt thông thường về ATTP\n"
                 "3. Tab 📅 Lịch & thông báo: xem lịch kiểm tra của Ban Giám Sát\n"
                 "4. Tab 🚨 Khẩn cấp: xem quy trình xử lý khi con có triệu chứng ngộ độc\n\n"
                 "Phụ huynh KHÔNG tự vào bếp kiểm tra nếu chưa được đào tạo và uỷ quyền."),
                ("👥 Ban Giám Sát (Đại Diện PHHS) — quy trình kiểm tra",
                 "1. Chọn vai trò 'Ban Giám Sát (Đại Diện PHHS)' và cấp trường\n"
                 "2. Tab ✅ Checklist: nhập thông tin buổi kiểm tra (trường, ngày, người kiểm tra)\n"
                 "3. Nhập thực đơn hôm nay → bấm 🤖 Tạo câu hỏi bổ sung (nếu có API)\n"
                 "4. Đánh giá lần lượt 20 điểm: chọn ✅ Đạt / ❌ Không Đạt / ghi chú\n"
                 "5. Chụp ảnh minh chứng ở mỗi nhóm (nếu có điểm KHÔNG ĐẠT bắt buộc cung cấp)\n"
                 "6. Tạo báo cáo Word → gửi cho Hiệu Trưởng trong 24 giờ\n"
                 "7. Tần suất: 2 lần/tuần (1 lần báo trước, 1 lần đột xuất)"),
                ("🏥 Y Tế Học Đường — kiểm thực 3 bước",
                 "Thực hiện mỗi ngày lúc 10:00 (30–45 phút trước bữa trưa):\n\n"
                 "Bước 1 — TRƯỚC chế biến: kiểm tra nguyên liệu đầu vào (tem kiểm dịch, hạn dùng, hóa đơn)\n"
                 "Bước 2 — TRONG chế biến: kiểm tra nhiệt độ nấu, vệ sinh dụng cụ, nhân viên\n"
                 "Bước 3 — SAU chế biến: kiểm tra nhiệt độ chia, màu mùi, khẩu phần, mẫu lưu\n\n"
                 "Ghi vào sổ kiểm thực (giấy bắt buộc theo TTLT 13/2016) + ghi vào app để lưu số."),
                ("🏫 Ban Giám Hiệu — xem tổng quan",
                 "1. Chọn vai trò 'Ban Giám Hiệu'\n"
                 "2. Nhận thông báo khi có báo cáo mới từ Ban Giám Sát\n"
                 "3. Xem mức cảnh báo: CRITICAL → xử lý ngay; MAJOR → trong ngày; MINOR → trong tuần\n"
                 "4. Ký duyệt báo cáo Word nhận được từ Ban Giám Sát\n"
                 "5. Tần suất xem: 1 lần/tuần tối thiểu"),
            ]
        },
        {
            "id": "checklist",
            "icon": "✅",
            "title": "3. Hướng dẫn Checklist 20 điểm",
            "content": (
                "Checklist 20 điểm được xây dựng theo NĐ 15/2018/NĐ-CP và TTLT 13/2016/TTLT-BYT-BGDĐT. "
                "Chia làm 5 nhóm, mỗi nhóm kiểm tra một khía cạnh của chuỗi thực phẩm."
            ),
            "subsections": [
                ("5 nhóm kiểm tra",
                 "📦 Nhóm 1 — Nguồn gốc nguyên liệu (C01–C04): tem kiểm dịch, hóa đơn, hạn dùng\n"
                 "🌡️ Nhóm 2 — Bảo quản & vận chuyển (C05–C08): nhiệt độ tủ lạnh, tách biệt sống/chín\n"
                 "🍽️ Nhóm 3 — Thức ăn khi phục vụ (C09–C13): nhiệt độ chia, thời gian nấu, khẩu phần\n"
                 "🧼 Nhóm 4 — Vệ sinh dụng cụ & nhân viên (C14–C17): dụng cụ sạch, bảo hộ\n"
                 "📋 Nhóm 5 — Hồ sơ & giấy tờ (C18–C20): sổ kiểm thực, thực đơn, mẫu lưu"),
                ("7 mục BẮT BUỘC — phải đạt tuyệt đối",
                 "C03 — Hạn sử dụng nguyên liệu ≥ 3 ngày\n"
                 "C07 — Nhiệt độ thức ăn khi nhận ≥ 60°C\n"
                 "C09 — Nhiệt độ thức ăn khi chia: nóng ≥ 60°C, lạnh ≤ 5°C\n"
                 "C10 — Thời gian nấu đến phục vụ < 2 giờ\n"
                 "C11 — Màu sắc và mùi thức ăn bình thường\n"
                 "C18 — Sổ kiểm thực 3 bước điền đầy đủ, có chữ ký\n"
                 "C20 — Có mẫu lưu thức ăn 24h từng món\n\n"
                 "⚠️ Nếu bất kỳ mục nào fail → mức cảnh báo tự động là CRITICAL bất kể điểm tổng."),
                ("Ngưỡng điểm và đánh giá tổng thể",
                 "18–20 điểm ĐẠT → ✅ Đạt chuẩn ATTP — lưu hồ sơ bình thường\n"
                 "15–17 điểm ĐẠT → ⚠️ Cần cải thiện — yêu cầu khắc phục trong 24h\n"
                 "< 15 điểm ĐẠT → ❌ Không đạt — báo ngay Ban Giám Hiệu"),
                ("Câu hỏi AI bổ sung theo thực đơn",
                 "Ngoài 20 câu chuẩn, khi nhập thực đơn và bấm 🤖 Tạo câu hỏi bổ sung, AI sẽ tạo "
                 "thêm 3–5 điểm kiểm tra đặc thù cho từng nguyên liệu dựa trên QCVN 8-1/8-2/8-3.\n\n"
                 "Ví dụ: thực đơn có cá → AI thêm check nhiệt độ bảo quản cá tươi theo QCVN 8-1.\n"
                 "Tính năng này CẦN credit API (~$0.004/lần). Không bấm → vẫn đánh giá đủ 20 câu."),
                ("Hướng dẫn chụp ảnh minh chứng",
                 "Khi nào cần ảnh: bắt buộc nếu có mục KHÔNG ĐẠT; khuyến khích cho tất cả các lần kiểm tra.\n\n"
                 "Chụp đạt chuẩn:\n"
                 "✅ Đủ sáng, không bóng đổ che khuất\n"
                 "✅ Cách 20–50cm, chụp thẳng góc\n"
                 "✅ Ảnh nét, không bị mờ\n"
                 "✅ Thấy rõ vùng cần kiểm tra\n"
                 "❌ Tránh: tối, mờ, nghiêng >45°, ảnh quá xa\n\n"
                 "AI phân tích ảnh (~$0.015/ảnh) phát hiện: màu bất thường, mốc, côn trùng, "
                 "sổ kiểm thực thiếu ký, thực phẩm để sai vị trí.\n"
                 "AI KHÔNG thể: phát hiện vi khuẩn vô hình, đo nhiệt độ thực, đảm bảo 100% chính xác."),
            ]
        },
        {
            "id": "alert",
            "icon": "🔔",
            "title": "4. Hệ thống cảnh báo 4 cấp",
            "subsections": [
                ("🔴 CRITICAL — Xử lý trong 5 phút",
                 "Kích hoạt khi: bất kỳ mục BẮT BUỘC nào fail, hoặc phát hiện ngộ độc ≥ 2 học sinh\n"
                 "Hành động: DỪNG bữa ăn ngay · Giữ mẫu thức ăn · Báo Hiệu Trưởng + 115 nếu cần\n"
                 "Thông báo: Hiệu Trưởng + Y Tế + Ban Giám Sát (Đại Diện PHHS) trong 5 phút"),
                ("🟠 MAJOR — Xử lý trong ngày",
                 "Kích hoạt khi: tổng điểm < 15/20, hoặc ≥ 3 mục KHÔNG ĐẠT cùng nhóm\n"
                 "Hành động: yêu cầu Nhà Cung Cấp khắc phục trước bữa ăn tiếp theo\n"
                 "Thông báo: Hiệu Trưởng + Y Tế Học Đường trong 2–4 giờ"),
                ("🟡 MINOR — Cải thiện trong tuần",
                 "Kích hoạt khi: tổng điểm 15–17/20\n"
                 "Hành động: ghi hồ sơ, yêu cầu cải thiện ở lần kiểm tra tiếp theo\n"
                 "Thông báo: Y Tế Học Đường + Nhà Cung Cấp trong 24–48 giờ"),
                ("✅ ĐẠT CHUẨN — Lưu hồ sơ",
                 "Điều kiện: tất cả mục BẮT BUỘC đều đạt VÀ tổng ≥ 18/20\n"
                 "Hành động: lưu báo cáo, báo cáo tổng hợp cuối tháng cho Hiệu Trưởng"),
            ]
        },
        {
            "id": "ai",
            "icon": "🤖",
            "title": "5. Tính năng AI — hướng dẫn và giới hạn",
            "subsections": [
                ("Cần credit API không?",
                 "CẦN credit (~$5 = dùng 1–2 tháng pilot):\n"
                 "• Hỏi đáp pháp luật: ~$0.003/câu\n"
                 "• Tạo checklist theo thực đơn: ~$0.004/lần\n"
                 "• Phân tích ảnh (Vision): ~$0.015/ảnh\n"
                 "• Báo cáo ngôn ngữ tự nhiên: ~$0.004/lần\n\n"
                 "KHÔNG cần credit (luôn dùng được):\n"
                 "• Checklist 20 câu · Xuất báo cáo Word · Lịch nhắc nhở · Hướng dẫn khẩn cấp"),
                ("AI phân tích ảnh hoạt động thế nào?",
                 "Ảnh được gửi đến Claude Opus (model AI đa phương thức của Anthropic). "
                 "AI đánh giá dựa trên tiêu chí cảm quan từ:\n"
                 "• WHO Food Safety Visual Inspection Guide\n"
                 "• QCVN 8-1:2011/BYT (dấu hiệu nhiễm vi sinh)\n"
                 "• NĐ 15/2018/NĐ-CP (điều kiện vệ sinh bếp ăn)\n\n"
                 "Kết quả trả về: mức rủi ro (OK/WARNING/CRITICAL), vấn đề phát hiện, "
                 "khuyến nghị khắc phục, căn cứ pháp lý áp dụng, độ tin cậy (%)."),
                ("Giới hạn quan trọng của AI",
                 "AI KHÔNG THỂ thay thế:\n"
                 "❌ Xét nghiệm vi sinh học (Salmonella, E.coli) — cần phòng thí nghiệm\n"
                 "❌ Đo nhiệt độ thực tế của thức ăn — cần nhiệt kế vật lý\n"
                 "❌ Ngửi mùi thực phẩm — cần người kiểm tra trực tiếp\n"
                 "❌ Đảm bảo 100% không có mối nguy — không có hệ thống nào làm được\n\n"
                 "AI phù hợp nhất cho: tạo hồ sơ, ghi nhận bằng chứng, hỗ trợ ra quyết định."),
            ]
        },
        {
            "id": "emergency",
            "icon": "🚨",
            "title": "6. Xử lý khẩn cấp ngộ độc thực phẩm",
            "content": "Quy trình 6 bước theo TTLT 13/2016/TTLT-BYT-BGDĐT:",
            "subsections": [
                ("Bước 1 — DỪNG BỮA ĂN NGAY",
                 "Yêu cầu toàn bộ học sinh ngừng ăn. Không để thêm bất kỳ ai ăn thêm."),
                ("Bước 2 — GỌI 115 nếu có triệu chứng nặng",
                 "Gọi 115 ngay khi học sinh có: co giật, khó thở, mất ý thức, nôn ra máu. "
                 "Không chờ đợi — mỗi phút là quan trọng."),
                ("Bước 3 — GIỮ NGUYÊN MẪU THỨC ĂN",
                 "KHÔNG vứt, KHÔNG rửa, KHÔNG đổ bất kỳ thức ăn nào. "
                 "Đây là bằng chứng duy nhất để xét nghiệm xác định nguyên nhân."),
                ("Bước 4 — BÁO NGAY Hiệu Trưởng + Y Tế học đường",
                 "Gọi điện trực tiếp, không nhắn tin. "
                 "Cung cấp: số học sinh bị, triệu chứng, giờ ăn, các món đã ăn."),
                ("Bước 5 — GHI CHÉP ĐẦY ĐỦ",
                 "Ghi ngay vào app (tab 🚨 Khẩn cấp → Bắt đầu xử lý sự cố) hoặc giấy: "
                 "số học sinh, triệu chứng, thời gian phát sinh, diễn biến."),
                ("Bước 6 — BÁO SỞ Y TẾ trong 24 giờ",
                 "Từ 2 người bị trở lên: bắt buộc báo Sở Y Tế địa phương trong 24h.\n"
                 "Đường dây nóng Cục ATTP: 1800 6838 (miễn phí, giờ hành chính)"),
            ]
        },
        {
            "id": "faq",
            "icon": "❓",
            "title": "7. Câu hỏi thường gặp (FAQ)",
            "faq": [
                ("Checklist 20 câu dựa trên luật nào?",
                 "NĐ 15/2018/NĐ-CP (điều kiện bếp ăn tập thể), TTLT 13/2016/TTLT-BYT-BGDĐT "
                 "(y tế trường học), QĐ 3958/QĐ-BYT 2025 (dinh dưỡng học đường), "
                 "QCVN 8-1/8-2/8-3 (giới hạn ô nhiễm vi sinh, kim loại nặng, thuốc trừ sâu)."),
                ("Nhà cung cấp từ chối cho xem sổ kiểm thực, phải làm sao?",
                 "Đây là vi phạm pháp luật. Sổ kiểm thực 3 bước là tài liệu bắt buộc theo TTLT 13/2016 "
                 "và phải được cung cấp khi Ban Giám Sát yêu cầu. "
                 "Ghi nhận vào báo cáo (C18 = KHÔNG ĐẠT) và báo Hiệu Trưởng + Sở Y Tế ngay."),
                ("Không có API key có dùng được app không?",
                 "Có. Checklist 20 câu, xuất báo cáo Word, lịch nhắc nhở, hướng dẫn khẩn cấp "
                 "hoàn toàn dùng được mà không cần API key hay credit. "
                 "Chỉ các tính năng AI (hỏi đáp pháp luật, phân tích ảnh, câu hỏi theo thực đơn) mới cần."),
                ("20 câu chuẩn hay câu hỏi AI bổ sung quan trọng hơn?",
                 "20 câu chuẩn là NỀN TẢNG — bắt buộc phải hoàn thành. "
                 "Câu hỏi AI bổ sung là THÊM VÀO — giúp phát hiện rủi ro đặc thù theo thực đơn hôm nay. "
                 "Không bấm tạo câu hỏi AI → vẫn đánh giá đầy đủ theo 20 câu."),
                ("AI phân tích ảnh có chính xác 100% không?",
                 "Không. AI phân tích dựa trên dấu hiệu nhìn thấy bằng mắt với độ tin cậy thường 75–90%. "
                 "Kết quả là gợi ý để người kiểm tra quyết định — không tự động thay thế phán xét của con người. "
                 "Với ảnh tốt (đủ sáng, nét, rõ), độ chính xác cao hơn."),
                ("Báo cáo Word gửi cho ai và lưu ở đâu?",
                 "Gửi cho: Hiệu Trưởng (trong 24h sau kiểm tra), Ban Giám Hiệu (để duyệt ký), "
                 "Sở GD&ĐT (khi được yêu cầu theo Điều 9 TTLT 13/2016). "
                 "Lưu: thư mục hồ sơ ATTP của trường (lưu tối thiểu 2 năm theo quy định)."),
                ("Phụ huynh có được vào bếp kiểm tra không?",
                 "Phụ huynh đơn lẻ KHÔNG có quyền tự vào bếp. "
                 "Ban Đại Diện Cha Mẹ Học Sinh (BĐDCMHS) được bầu chính thức mới có quyền "
                 "giám sát định kỳ theo quy chế dân chủ và TTLT 13/2016."),
                ("Khoảng cách giữa hai lần kiểm tra là bao nhiêu?",
                 "Ban Giám Sát (Đại Diện PHHS): tối thiểu 2 lần/tuần (1 báo trước ≥24h, 1 đột xuất). "
                 "Y Tế Học Đường: mỗi ngày có bữa ăn, lúc 10:00. "
                 "Ban Giám Hiệu: 1 lần/tháng (tuần cuối tháng). "
                 "Sở GD&ĐT/Sở Y Tế: 1–2 lần/học kỳ (đột xuất)."),
                ("Vùng nhiệt độ nguy hiểm là gì?",
                 "5°C – 60°C là vùng nhiệt độ vi khuẩn phát triển nhanh nhất "
                 "(tăng gấp đôi mỗi 20 phút ở nhiệt độ phòng). "
                 "Thức ăn nóng phải ≥60°C; thức ăn lạnh phải ≤5°C; "
                 "thức ăn đã nấu không được để ở nhiệt độ phòng quá 2 giờ."),
                ("Mẫu lưu thức ăn (lưu nghiệm) là gì và cần lưu bao lâu?",
                 "Mỗi món ăn trong bữa cần lấy ≥100g làm mẫu, cho vào túi kín, ghi nhãn "
                 "(tên món + giờ lấy + ngày), bảo quản trong tủ lạnh ≤5°C. "
                 "Lưu tối thiểu 24 giờ sau bữa ăn. Dùng để xét nghiệm khi nghi ngờ ngộ độc."),
            ]
        },
        {
            "id": "legal",
            "icon": "⚖️",
            "title": "8. Căn cứ pháp lý tóm tắt",
            "legal_refs": [
                ("Luật ATTP số 55/2010/QH12",
                 "Khung pháp lý tổng thể về an toàn thực phẩm tại Việt Nam. "
                 "Điều quan trọng: Điều 53 — nghĩa vụ báo cáo ngộ độc thực phẩm."),
                ("Nghị định 15/2018/NĐ-CP",
                 "Điều kiện đảm bảo ATTP cho cơ sở sản xuất kinh doanh thực phẩm, bao gồm bếp ăn tập thể. "
                 "Điều quan trọng: Điều 11–15 về điều kiện bếp ăn tập thể và nhà cung cấp suất ăn."),
                ("TTLT 13/2016/TTLT-BYT-BGDĐT",
                 "Công tác y tế trường học, bao gồm kiểm soát ATTP bữa ăn học đường. "
                 "Điều quan trọng: Điều 9 về kiểm thực 3 bước và lưu mẫu thức ăn."),
                ("Quyết định 3958/QĐ-BYT ngày 25/12/2025",
                 "Hướng dẫn dinh dưỡng bữa ăn học đường (văn bản mới nhất). "
                 "Quy định khẩu phần năng lượng, protein, rau theo từng cấp học."),
                ("QCVN 8-1:2011/BYT",
                 "Giới hạn ô nhiễm vi sinh vật (Salmonella, E.coli, Staphylococcus aureus, v.v.) "
                 "trong từng loại thực phẩm."),
                ("QCVN 8-2:2011/BYT",
                 "Giới hạn ô nhiễm kim loại nặng (chì, cadimi, thuỷ ngân, asen) trong thực phẩm."),
                ("Nghị định 115/2018/NĐ-CP",
                 "Mức xử phạt vi phạm hành chính về ATTP. "
                 "Phạt từ 10–100 triệu đồng; gây tử vong → xử lý hình sự."),
            ]
        },
        {
            "id": "glossary",
            "icon": "📚",
            "title": "9. Bảng thuật ngữ",
            "terms": [
                ("ATTP", "An toàn thực phẩm"),
                ("ATVSTP", "An toàn vệ sinh thực phẩm (cách gọi cũ, nay dùng ATTP)"),
                ("PHHS", "Phụ huynh học sinh"),
                ("Ban Đại Diện PHHS (BĐDCMHS)", "Ban Đại Diện Cha Mẹ Học Sinh — tổ chức đại diện chính thức của phụ huynh"),
                ("Kiểm thực 3 bước", "Quy trình kiểm tra thực phẩm trước/trong/sau chế biến theo luật"),
                ("Lưu mẫu / Lưu nghiệm", "Giữ lại mẫu thức ăn 24h để xét nghiệm nếu cần"),
                ("Vùng nhiệt độ nguy hiểm", "5°C – 60°C: vi khuẩn tăng gấp đôi mỗi 20 phút"),
                ("HACCP", "Phân tích mối nguy và kiểm soát điểm tới hạn — tiêu chuẩn quốc tế"),
                ("Codex Alimentarius", "Bộ tiêu chuẩn thực phẩm quốc tế của FAO/WHO"),
                ("Claude Vision", "Mô hình AI đa phương thức của Anthropic — phân tích hình ảnh"),
                ("CRITICAL / MAJOR / MINOR", "Ba cấp độ cảnh báo trong app (tới hạn / nghiêm trọng / nhỏ)"),
                ("API key", "Mật khẩu truy cập dịch vụ AI — lấy tại console.anthropic.com"),
                ("Credit", "Tín dụng thanh toán API AI — $5 dùng được khoảng 1–2 tháng pilot"),
            ]
        },
    ]
}


# ── Render nội dung sổ tay trong tab ─────────────────────────────────────────
def tab_guide():
    """Tab hướng dẫn sử dụng đầy đủ — sổ tay điện tử tích hợp trong app."""
    mc = MANUAL_CONTENT
    st.markdown(f"""<div class="sf-card">
        <div class="sf-card-title">📖 {mc['title']}</div>
        <div class="sf-card-body">{mc['subtitle']} · {mc['version']}</div>
    </div>""", unsafe_allow_html=True)

    # Nút tải sổ tay Word
    if st.button("⬇️ Tải Sổ Tay PDF/Word (.docx) để in và đào tạo",
                 type="primary", use_container_width=True):
        with st.spinner("Đang tạo file Word..."):
            docx_bytes = generate_manual_docx()
        st.download_button(
            "📥 Tải ngay — Sổ Tay SchoolFood AI.docx",
            data=docx_bytes,
            file_name="So_Tay_SchoolFood_AI_v2.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)

    # Render từng section
    for section in mc["sections"]:
        with st.expander(f"{section['icon']} {section['title']}", expanded=False):
            if "content" in section:
                st.markdown(section["content"])

            if "subsections" in section:
                for sub_title, sub_content in section["subsections"]:
                    st.markdown(
                        f'<div style="background:#F8FAFC;border-left:3px solid #2563EB;'
                        f'border-radius:0 8px 8px 0;padding:10px 14px;margin:8px 0">'
                        f'<b style="color:#1E293B;font-size:0.9rem">{sub_title}</b>'
                        f'</div>', unsafe_allow_html=True
                    )
                    # Render nội dung với line breaks
                    for line in sub_content.split("\n"):
                        if line.strip():
                            st.markdown(
                                f'<div style="font-size:0.875rem;color:#334155;'
                                f'padding:2px 14px;line-height:1.65">{line}</div>',
                                unsafe_allow_html=True
                            )
                    st.markdown("")

            # FAQ
            if "faq" in section:
                for q, a in section["faq"]:
                    with st.expander(f"❓ {q}"):
                        st.markdown(
                            f'<div style="font-size:0.875rem;color:#334155;line-height:1.7">{a}</div>',
                            unsafe_allow_html=True
                        )

            # Căn cứ pháp lý
            if "legal_refs" in section:
                for name, desc in section["legal_refs"]:
                    st.markdown(
                        f'<div class="sf-card" style="padding:12px 16px;margin:6px 0">'
                        f'<span class="role-tag">{name}</span>'
                        f'<div style="font-size:0.83rem;color:#475569;margin-top:6px">{desc}</div>'
                        f'</div>', unsafe_allow_html=True
                    )

            # Thuật ngữ
            if "terms" in section:
                for term, definition in section["terms"]:
                    st.markdown(
                        f'<div style="display:flex;gap:12px;padding:5px 0;'
                        f'border-bottom:1px solid #F1F5F9;font-size:0.875rem">'
                        f'<span style="min-width:180px;font-weight:700;color:#1E293B">{term}</span>'
                        f'<span style="color:#475569">{definition}</span>'
                        f'</div>', unsafe_allow_html=True
                    )


# ── Tạo sổ tay Word chuyên nghiệp ─────────────────────────────────────────────
def generate_manual_docx() -> bytes:
    """Tạo file Word sổ tay hướng dẫn chuẩn hành chính, font Times New Roman."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from io import BytesIO

    mc  = MANUAL_CONTENT
    doc = Document()

    # Lề trang
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    sec.left_margin = Cm(3.0); sec.right_margin = Cm(2.0)

    # Bìa
    _docx_para(doc, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
               bold=True, size=13, align="center", space_after=2)
    _docx_para(doc, "Độc lập – Tự do – Hạnh phúc",
               bold=True, size=12, align="center", space_after=2)
    _docx_para(doc, "────────────────────────────────",
               size=11, align="center", space_after=20)
    _docx_para(doc, mc["title"], bold=True, size=16, align="center",
               space_before=10, space_after=6)
    _docx_para(doc, mc["subtitle"], bold=True, size=13, align="center", space_after=4)
    _docx_para(doc, mc["version"], size=12, align="center", space_after=30)
    _docx_para(doc, "Dành cho: Phụ Huynh · Ban Giám Sát (Đại Diện PHHS) · Y Tế Học Đường · Ban Giám Hiệu",
               size=12, align="center", space_after=4)
    _docx_para(doc, f"Cập nhật: {now_vn().strftime('%d/%m/%Y')}",
               size=11, align="center", space_after=4)
    _docx_para(doc, "Đường dây nóng Cục ATTP: 1800 6838 (miễn phí) | Cấp cứu: 115",
               bold=True, size=12, align="center", space_after=0)

    doc.add_page_break()

    # Mục lục
    _docx_para(doc, "MỤC LỤC", bold=True, size=14, align="center",
               space_before=0, space_after=10)
    for section in mc["sections"]:
        _docx_para(doc, f"  {section['title']}", size=12, space_after=4)
    doc.add_page_break()

    # Nội dung từng section
    for section in mc["sections"]:
        _docx_para(doc, f"{section['icon']}  {section['title']}",
                   bold=True, size=14, space_before=12, space_after=6)

        if "content" in section:
            for para in section["content"].split("\n\n"):
                if para.strip():
                    _docx_para(doc, para.strip(), size=12, align="justify",
                               space_after=4)

        if "subsections" in section:
            for sub_title, sub_content in section["subsections"]:
                _docx_para(doc, sub_title, bold=True, size=12,
                           space_before=6, space_after=3)
                for line in sub_content.split("\n"):
                    if line.strip():
                        _docx_para(doc, line, size=11, align="justify",
                                   space_after=2)

        if "faq" in section:
            for q, a in section["faq"]:
                _docx_para(doc, f"Hỏi: {q}", bold=True, size=12,
                           space_before=6, space_after=2)
                _docx_para(doc, f"Đáp: {a}", size=11, align="justify",
                           space_after=4)

        if "legal_refs" in section:
            for name, desc in section["legal_refs"]:
                _docx_para(doc, name, bold=True, size=12, space_before=4, space_after=2)
                _docx_para(doc, desc, size=11, align="justify", space_after=4)

        if "terms" in section:
            tbl = doc.add_table(rows=1 + len(section["terms"]), cols=2)
            tbl.style = "Table Grid"
            _docx_table_header(tbl, ["Thuật ngữ / Ký hiệu", "Giải thích"])
            for i, (term, definition) in enumerate(section["terms"]):
                r0 = tbl.rows[i+1].cells[0].paragraphs[0].add_run(term)
                r1 = tbl.rows[i+1].cells[1].paragraphs[0].add_run(definition)
                _docx_set_font(r0, bold=True, size_pt=11)
                _docx_set_font(r1, size_pt=11)

        doc.add_paragraph()

    # Trang cuối
    doc.add_page_break()
    _docx_para(doc, "─" * 50, size=10, align="center", space_before=20, space_after=6)
    _docx_para(doc, f"Sổ tay được tạo tự động bởi SchoolFood AI v2.0",
               size=10, align="center", space_after=2)
    _docx_para(doc, f"Ngày tạo: {now_vn().strftime('%d/%m/%Y %H:%M')} (GMT+7)",
               size=10, align="center", space_after=2)
    _docx_para(doc, "Thông tin tham khảo — vui lòng xác nhận với cơ quan có thẩm quyền khi cần thiết",
               size=9, align="center", space_after=0)

    buf = BytesIO(); doc.save(buf); buf.seek(0)
    return buf.read()


def tab_history(role: str = "", school_filter: str = ""):
    """Live dashboard chuyên nghiệp — biểu đồ cột, tròn, đường, phân bố."""
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from io import BytesIO

    st.markdown("""<div class="sf-card">
        <div class="sf-card-title">📊 Live Dashboard — Lịch sử kiểm tra ATTP</div>
        <div class="sf-card-body">
            Dữ liệu realtime từ database · Biểu đồ tương tác · Xuất Excel chuẩn
        </div>
    </div>""", unsafe_allow_html=True)

    # Thử kết nối và hiện lỗi cụ thể
    _get_sb()  # Trigger kết nối để lấy error message
    if not db_ok():
        err = db_error_msg()
        # Kiểm tra xem secrets có tồn tại không
        has_url = bool(st.secrets.get("SUPABASE_URL", "") if hasattr(st, "secrets") else "")
        has_key = bool(st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else "")
        diag = []
        if not has_url: diag.append("❌ SUPABASE_URL chưa có trong Secrets")
        if not has_key: diag.append("❌ SUPABASE_ANON_KEY chưa có trong Secrets")
        if has_url and has_key: diag.append("✅ Secrets có đủ 2 key — nhưng kết nối thất bại")
        diag_html = "<br>".join(diag)

        st.markdown(
            f'<div style="background:#FFF7ED;border:2px solid #FB923C;border-radius:12px;'
            f'padding:20px 24px">'
            f'<div style="font-size:1.1rem;font-weight:700;color:#9A3412;margin-bottom:8px">'
            f'📦 Database chưa được kết nối</div>'
            f'<div style="font-size:0.88rem;color:#7C2D12;line-height:1.9">'
            f'{diag_html}<br>'
            f'{"<b>Lỗi chi tiết:</b> " + err if err else ""}'
            f'</div>'
            f'<div style="margin-top:12px;font-size:0.82rem;color:#92400E">'
            f'Thêm vào Streamlit Secrets (Settings → Secrets):<br>'
            f'<code style="background:#FED7AA;padding:2px 8px;border-radius:4px;display:block;margin:4px 0">'
            f'SUPABASE_URL = "https://vmvensiremofatkylcuw.supabase.co"</code>'
            f'<code style="background:#FED7AA;padding:2px 8px;border-radius:4px;display:block;margin:4px 0">'
            f'SUPABASE_ANON_KEY = "eyJhbGci..."</code>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        return

    # Lọc theo trường
    col_f, col_r = st.columns([3, 1])
    school_input = col_f.text_input(
        "Lọc theo tên trường (để trống = tất cả)",
        value=school_filter, placeholder="VD: TH Nguyễn Du"
    )
    check_type = col_r.selectbox("Loại kiểm tra", [
        "Tất cả", "ban_giam_sat", "kiem_thuc_3_buoc"
    ])

    sessions = db_get_sessions(school=school_input.strip(), limit=100)
    if check_type != "Tất cả":
        sessions = [s for s in sessions if s.get("check_type") == check_type]

    if not sessions:
        st.info("Chưa có dữ liệu lịch sử. Thực hiện kiểm tra và tạo báo cáo lần đầu.")
        return

    # ── Chuẩn bị dataframe ────────────────────────────────────────────────────
    ALERT_VN = {"OK":"Đạt chuẩn","MINOR":"Cần cải thiện","MAJOR":"Không đạt","CRITICAL":"Nguy hiểm"}
    TYPE_VN  = {"ban_giam_sat":"Ban Giám Sát","kiem_thuc_3_buoc":"Y Tế (3 bước)","nha_cung_cap":"Nhà cung cấp"}

    rows = []
    for s in sessions:
        pct = s.get("pass_count",0) / max(s.get("total_items",20),1) * 100
        rows.append({
            "Ngày":           s.get("check_date",""),
            "Trường":         s.get("school_name",""),
            "Người kiểm tra": s.get("inspector_name",""),
            "Loại kiểm tra":  TYPE_VN.get(s.get("check_type",""),s.get("check_type","")),
            "Tỷ lệ đạt (%)":  round(pct,1),
            "Điểm đạt":       s.get("pass_count",0),
            "Điểm không đạt": s.get("fail_count",0),
            "Tổng điểm":      s.get("total_items",20),
            "Cấp cảnh báo":   s.get("alert_level",""),
            "Đánh giá":       ALERT_VN.get(s.get("alert_level",""), s.get("alert_level","")),
        })
    df = pd.DataFrame(rows)

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    total   = len(df)
    avg_pct = df["Tỷ lệ đạt (%)"].mean()
    crit_ct = (df["Cấp cảnh báo"] == "CRITICAL").sum()
    ok_ct   = (df["Cấp cảnh báo"] == "OK").sum()

    # ── Tính trạng thái xu hướng (trực quan, không dùng số %) ───────────────
    n_split    = max(1, len(df) // 3)
    recent_avg = df.head(n_split)["Tỷ lệ đạt (%)"].mean()
    older_avg  = df.tail(n_split)["Tỷ lệ đạt (%)"].mean()
    delta      = recent_avg - older_avg

    if abs(delta) < 1:
        if avg_pct >= 90:
            trend_icon, trend_text, trend_bg, trend_tc = "✅", "Đang tốt",       "#DCFCE7", "#16A34A"
        else:
            trend_icon, trend_text, trend_bg, trend_tc = "⚠️", "Cần theo dõi",   "#FEF9C3", "#CA8A04"
    elif delta > 0:
        trend_icon, trend_text, trend_bg, trend_tc     = "📈", "Đang cải thiện", "#DBEAFE", "#2563EB"
    else:
        trend_icon, trend_text, trend_bg, trend_tc     = "📉", "Đang giảm",      "#FEE2E2", "#DC2626"

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)

    # 4 metric số liệu bình thường
    for col, val, lbl, clr in [
        (k1, str(total),          "Tổng lần kiểm tra",    "c-blue"),
        (k2, f"{avg_pct:.0f}%",   "Trung bình đạt",       "c-green" if avg_pct>=90 else "c-orange"),
        (k3, str(crit_ct),        "Mức độ CRITICAL",      "c-red" if crit_ct>0 else "c-green"),
        (k4, str(ok_ct),          "Đạt chuẩn",            "c-green"),
    ]:
        col.markdown(
            f'<div class="metric-box" style="text-align:center">'
            f'<div class="metric-lbl">{lbl}</div>'
            f'<div class="metric-num {clr}" style="font-size:2rem;text-align:center">{val}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Metric xu hướng — icon + text trong cùng 1 metric-num để giữ chiều cao bằng 4 ô còn lại
    k5.markdown(
        f'<div class="metric-box" style="text-align:center;background:{trend_bg};'
        f'border:1px solid {trend_tc}">'
        f'<div class="metric-lbl">Xu hướng</div>'
        f'<div class="metric-num" style="font-size:1.5rem;color:{trend_tc};line-height:1.2">'
        f'{trend_icon}<br>'
        f'<span style="font-size:0.75rem;font-weight:700">{trend_text}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Hàng 1: Xu hướng + Phân bố ───────────────────────────────────────────
    _CHART_LAYOUT = dict(
        plot_bgcolor="white", paper_bgcolor="#F8FAFC",
        font=dict(family="Inter, sans-serif", size=12, color="#334155"),
        title_font=dict(size=14, color="#1B3B6F", family="Inter"),
        margin=dict(l=16, r=16, t=40, b=16),
    )
    ch1, ch2 = st.columns([3, 2])

    with ch1:
        # Tổng hợp theo ngày: 1 điểm/ngày (trung bình tất cả trường trong ngày đó)
        df_agg = (
            df.groupby("Ngày")["Tỷ lệ đạt (%)"]
            .mean()
            .reset_index()
            .sort_values("Ngày")
            .tail(30)
        )
        # Đảm bảo định dạng ngày là dd/mm/yyyy (tránh hiển thị timestamp)
        try:
            df_agg["Ngày_fmt"] = pd.to_datetime(df_agg["Ngày"]).dt.strftime("%d/%m")
        except Exception:
            df_agg["Ngày_fmt"] = df_agg["Ngày"]

        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=df_agg["Ngày_fmt"],
            y=df_agg["Tỷ lệ đạt (%)"].round(1),
            mode="lines+markers+text",
            line=dict(color="#2563EB", width=3, shape="spline"),
            marker=dict(size=10, color="#2563EB",
                        line=dict(width=2.5, color="white")),
            text=[f"{v:.0f}%" for v in df_agg["Tỷ lệ đạt (%)"]],
            textposition="top center",
            textfont=dict(size=12, color="#1E293B", family="Inter"),
            hovertemplate="Ngày %{x}<br>Tỷ lệ đạt: <b>%{y:.1f}%</b><extra></extra>",
        ))
        fig_line.add_hline(
            y=90, line_dash="dot", line_color="#DC2626", line_width=2,
            annotation_text=" Ngưỡng chuẩn 90%",
            annotation_font=dict(color="#DC2626", size=11, family="Inter"),
            annotation_position="bottom right",
        )
        # Tô vùng đạt chuẩn (>90%) màu xanh nhạt
        fig_line.add_hrect(
            y0=90, y1=110, fillcolor="#DCFCE7", opacity=0.15,
            layer="below", line_width=0,
        )
        fig_line.update_layout(
            **_CHART_LAYOUT, height=320,
            title="📈 Xu hướng tỷ lệ đạt theo ngày (điểm trung bình/ngày)",
            xaxis=dict(title="Ngày kiểm tra", showgrid=False,
                       tickangle=0 if len(df_agg) <= 10 else -30,
                       tickfont=dict(size=11)),
            yaxis=dict(title="Tỷ lệ đạt (%)", range=[0,110], ticksuffix="%",
                       showgrid=True, gridcolor="#E2E8F0", dtick=20),
            showlegend=False,
        )
        st.plotly_chart(fig_line, use_container_width=True)

    with ch2:
        alert_counts = df["Đánh giá"].value_counts().reset_index()
        alert_counts.columns = ["Mức", "Số lần"]
        fig_pie = go.Figure(go.Pie(
            labels=alert_counts["Mức"], values=alert_counts["Số lần"],
            hole=0.45,
            marker_colors=[
                {"Đạt chuẩn":"#16A34A","Cần cải thiện":"#F59E0B",
                 "Không đạt":"#D97706","Nguy hiểm":"#DC2626"}.get(m,"#64748B")
                for m in alert_counts["Mức"]
            ],
            textfont_size=13,
            textinfo="percent+label",
            hovertemplate="%{label}<br>%{value} lần (%{percent})<extra></extra>",
        ))
        fig_pie.update_layout(
            **_CHART_LAYOUT, height=320,
            title="🥧 Phân bố mức cảnh báo",
            showlegend=False,
            annotations=[dict(text=f"<b>{total}</b><br><span style='font-size:11px'>lần</span>",
                              x=0.5, y=0.5, showarrow=False, font_size=15, font_color="#1E293B")],
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    # ── Hàng 2: Cột theo tuần + Histogram ────────────────────────────────────
    ch3, ch4 = st.columns([3, 2])

    with ch3:
        try:
            df_wk = df.copy()
            _wk_dt = pd.to_datetime(df_wk["Ngày"], errors="coerce")
            _wk_periods = _wk_dt.dt.to_period("W")
            df_wk["Tuần"] = _wk_periods.apply(
                lambda p: f"{p.start_time.strftime('%d/%m')}-{p.end_time.strftime('%d/%m')}"
                if pd.notna(p) else "?"
            )
            # Giữ thứ tự tuần tăng dần
            _week_order = (
                _wk_periods.dropna()
                .sort_values()
                .unique()
            )
            _week_labels = [
                f"{p.start_time.strftime('%d/%m')}-{p.end_time.strftime('%d/%m')}"
                for p in _week_order
            ]
            wk_cnt = df_wk.groupby(["Tuần","Đánh giá"]).size().reset_index(name="Số lần")
            # Màu: xanh = đạt chuẩn, vàng = cần cải thiện, cam = không đạt, đỏ = nguy hiểm
            _COLOR_MAP = {
                "Đạt chuẩn":    "#16A34A",
                "Cần cải thiện":"#F59E0B",
                "Không đạt":    "#F97316",
                "Nguy hiểm":    "#DC2626",
            }
            fig_bar = px.bar(
                wk_cnt, x="Tuần", y="Số lần", color="Đánh giá",
                color_discrete_map=_COLOR_MAP,
                barmode="stack", text="Số lần",
                category_orders={"Tuần": _week_labels},
            )
            fig_bar.update_traces(textposition="inside", textfont_size=12)
            fig_bar.update_layout(
                **{**_CHART_LAYOUT, "margin": dict(l=16, r=130, t=40, b=16)},
                height=320,
                title="📊 Số lần kiểm tra theo tuần",
                xaxis=dict(title="Tuần", tickangle=-20, showgrid=False,
                           tickfont=dict(size=11)),
                yaxis=dict(title="Số lần kiểm tra", showgrid=True, gridcolor="#E2E8F0"),
                legend=dict(
                    orientation="v", x=1.02, y=0.5,
                    xanchor="left", yanchor="middle",
                    title_text="Đánh giá",
                    bgcolor="rgba(255,255,255,0.8)",
                    bordercolor="#E2E8F0", borderwidth=1,
                ),
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        except Exception as _e:
            st.info(f"Cần thêm dữ liệu để hiển thị biểu đồ theo tuần. ({_e})")

    with ch4:
        # So sánh tỷ lệ đạt trung bình theo loại kiểm tra
        type_stats = (
            df.groupby("Loại kiểm tra")
            .agg(avg_pct=("Tỷ lệ đạt (%)", "mean"),
                 count=("Tỷ lệ đạt (%)", "count"))
            .reset_index()
            .sort_values("avg_pct", ascending=True)
        )
        _t_clrs = [
            "#16A34A" if v >= 90 else "#F59E0B" if v >= 80 else "#F97316"
            for v in type_stats["avg_pct"]
        ]
        fig_type = go.Figure(go.Bar(
            x=type_stats["avg_pct"].round(1),
            y=type_stats["Loại kiểm tra"],
            orientation="h",
            marker_color=_t_clrs,
            text=[f"{v:.0f}%  ({c} lần)"
                  for v, c in zip(type_stats["avg_pct"], type_stats["count"])],
            textposition="outside",
            textfont=dict(size=12, color="#1E293B"),
            hovertemplate="<b>%{y}</b><br>Tỷ lệ đạt TB: <b>%{x:.1f}%</b><extra></extra>",
        ))
        fig_type.add_vline(
            x=90, line_dash="dot", line_color="#DC2626", line_width=1.5,
            annotation_text=" Chuẩn 90%",
            annotation_font=dict(size=11, color="#DC2626"),
            annotation_position="top",
        )
        fig_type.update_layout(
            **{**_CHART_LAYOUT, "margin": dict(l=10, r=90, t=40, b=16)},
            height=320,
            title="🔍 Tỷ lệ đạt TB theo loại kiểm tra",
            xaxis=dict(title="Tỷ lệ đạt (%)", range=[0, 120],
                       ticksuffix="%", showgrid=True, gridcolor="#E2E8F0"),
            yaxis=dict(title="", showgrid=False,
                       tickfont=dict(size=12), automargin=True),
            showlegend=False,
        )
        st.plotly_chart(fig_type, use_container_width=True)

    # ── Hàng 3: Điểm FAIL nhiều nhất ─────────────────────────────────────────
    st.markdown('<div class="sec-hdr">🔴 Top 10 điểm không đạt nhiều nhất</div>',
                unsafe_allow_html=True)
    try:
        sb = _get_sb()
        if not sb:
            st.warning("Không kết nối được database để tải dữ liệu top fail.")
        else:
            # Thử cả 2 dạng lưu: có emoji và không emoji
            _resp = sb.table("checklist_results")\
                .select("item_code,result,item_desc")\
                .in_("result", ["Không Đạt", "❌ Không Đạt"])\
                .limit(500).execute()
            items_raw = _resp.data or []

            if not items_raw:
                st.info("Chưa có dữ liệu điểm không đạt. Thực hiện kiểm tra để thống kê.")
            else:
                df_it = pd.DataFrame(items_raw)

                # Từ khoá ngắn gọn theo mã tiêu chí
                _KEYWORD_MAP = {
                    "C01": "Tem kiểm dịch thịt/cá",
                    "C02": "Hóa đơn nguồn gốc rau củ",
                    "C03": "Hạn sử dụng nguyên liệu",
                    "C04": "Hóa đơn mua hàng ngày",
                    "C05": "Nhiệt độ tủ lạnh < 5°C",
                    "C06": "Tách biệt thực phẩm sống/chín",
                    "C07": "Nhiệt độ nhận hàng ≥ 60°C",
                    "C08": "Thùng vận chuyển kín, sạch",
                    "C09": "Nhiệt độ chia ăn đúng chuẩn",
                    "C10": "Thời gian nấu → phục vụ < 2h",
                    "C11": "Màu sắc & mùi vị thức ăn",
                    "C12": "Khẩu phần thịt/cá đủ định mức",
                    "C13": "Khẩu phần rau xanh đủ định mức",
                    "C14": "Dụng cụ ăn sạch, khô ráo",
                    "C15": "Đeo khẩu trang & găng tay",
                    "C16": "Không ho/hắt hơi vào thức ăn",
                    "C17": "Khu vực chia cơm sạch, không côn trùng",
                    "C18": "Sổ kiểm thực 3 bước đủ chữ ký",
                    "C19": "Thực đơn khớp đăng ký",
                    "C20": "Mẫu lưu thức ăn 24h đủ nhãn",
                    "B1_01": "Tem kiểm dịch thịt/cá (B1)",
                    "B1_02": "Hóa đơn rau củ nguồn gốc (B1)",
                    "B1_03": "Hạn sử dụng nguyên liệu (B1)",
                    "B1_04": "Nhiệt độ tủ lạnh < 5°C (B1)",
                    "B1_05": "Tách biệt sống/chín (B1)",
                    "B2_01": "Nấu chín ≥ 70°C (B2)",
                    "B2_02": "Bảo hộ lao động bếp (B2)",
                    "B2_03": "Dao thớt riêng sống/chín (B2)",
                    "B2_04": "Dụng cụ nấu sạch, nguyên vẹn (B2)",
                    "B2_05": "Bếp sạch, không côn trùng (B2)",
                    "B3_01": "Nhiệt độ chia đúng chuẩn (B3)",
                    "B3_02": "Thời gian nấu → chia < 2h (B3)",
                    "B3_03": "Màu sắc & mùi vị ổn (B3)",
                    "B3_04": "Khẩu phần đủ định mức (B3)",
                    "B3_05": "Mẫu lưu 24h đủ nhãn (B3)",
                }

                def _get_label(row):
                    code = row.get("item_code", "?")
                    return _KEYWORD_MAP.get(code, code)

                df_it["Tên điểm"] = df_it.apply(_get_label, axis=1)
                top_fail = (
                    df_it.groupby("Tên điểm")
                    .size()
                    .reset_index(name="Số lần không đạt")
                    .sort_values("Số lần không đạt")
                    .tail(10)
                )
                n = len(top_fail)
                colors = [
                    f"rgba(220,38,38,{0.25 + 0.75*i/max(n-1,1)})"
                    for i in range(n)
                ]
                fig_hbar = go.Figure(go.Bar(
                    x=top_fail["Số lần không đạt"],
                    y=top_fail["Tên điểm"],
                    orientation="h",
                    marker_color=colors,
                    text=top_fail["Số lần không đạt"],
                    textposition="outside",
                    textfont=dict(size=12),
                    hovertemplate="<b>%{y}</b><br>Không đạt: %{x} lần<extra></extra>",
                ))
                fig_hbar.update_layout(
                    **{**_CHART_LAYOUT, "margin": dict(l=10, r=60, t=20, b=16)},
                    height=max(300, n * 52),
                    title="",
                    xaxis=dict(title="Số lần không đạt", showgrid=True,
                               gridcolor="#E2E8F0", dtick=1),
                    yaxis=dict(title="", showgrid=False,
                               tickfont=dict(size=11), automargin=True),
                )
                st.plotly_chart(fig_hbar, use_container_width=True)
    except Exception as _top_err:
        st.warning(f"Không thể tải biểu đồ top fail: {_top_err}")

    # ── Bảng chi tiết + Xuất Excel chuẩn (Times New Roman, cỡ 13) ────────────
    st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr">📋 Bảng chi tiết</div>', unsafe_allow_html=True)
    df_display = df.drop(columns=["Cấp cảnh báo"], errors="ignore").copy()
    _parsed = pd.to_datetime(df_display["Ngày"], errors="coerce", dayfirst=False)
    df_display["Ngày"] = _parsed.dt.strftime("%d/%m/%Y").where(_parsed.notna(), df_display["Ngày"])
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.markdown('<div class="sec-hdr">⬇️ Xuất báo cáo</div>', unsafe_allow_html=True)

    # Tạo Excel với định dạng chuyên nghiệp Times New Roman 13
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font as XFont, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb  = Workbook()
        ws  = wb.active
        ws.title = "Lịch sử kiểm tra ATTP"

        # Quốc hiệu
        ws.merge_cells(f"A1:{get_column_letter(len(df_display.columns))}1")
        c = ws["A1"]
        c.value = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM — Độc lập – Tự do – Hạnh phúc"
        c.font      = XFont(name="Times New Roman", size=11, bold=True)
        c.alignment = Alignment(horizontal="center")
        ws.row_dimensions[1].height = 18

        # Tiêu đề
        ws.merge_cells(f"A2:{get_column_letter(len(df_display.columns))}2")
        c = ws["A2"]
        c.value = "BÁO CÁO LỊCH SỬ KIỂM TRA AN TOÀN THỰC PHẨM BỮA ĂN HỌC ĐƯỜNG"
        c.font      = XFont(name="Times New Roman", size=15, bold=True, color="1B3B6F")
        c.alignment = Alignment(horizontal="center")
        ws.row_dimensions[2].height = 28

        # Subtitle
        ws.merge_cells(f"A3:{get_column_letter(len(df_display.columns))}3")
        c = ws["A3"]
        c.value = (f"Xuất ngày: {now_vn().strftime('%d/%m/%Y %H:%M')} | "
                   f"Tổng: {total} lần kiểm tra | Trung bình đạt: {avg_pct:.0f}%")
        c.font      = XFont(name="Times New Roman", size=11, italic=True, color="475569")
        c.alignment = Alignment(horizontal="center")
        ws.row_dimensions[3].height = 16

        # Header row
        HDR_FILL = PatternFill("solid", fgColor="1B3B6F")
        HDR_FONT = XFont(name="Times New Roman", size=13, bold=True, color="FFFFFF")
        HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
        THIN_SIDE = Side(style="thin", color="CBD5E1")
        BORDER    = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)

        for ci, col_name in enumerate(df_display.columns, 1):
            c = ws.cell(row=4, column=ci, value=col_name)
            c.font = HDR_FONT; c.fill = HDR_FILL
            c.alignment = HDR_ALIGN; c.border = BORDER
        ws.row_dimensions[4].height = 22

        # Data rows
        ALERT_COLORS = {
            "Nguy hiểm":     "FEE2E2",
            "Không đạt":     "FEF9C3",
            "Cần cải thiện": "FEFCE8",
        }

        for ri, row_data in enumerate(df_display.itertuples(index=False), 5):
            row_vals = list(row_data)
            alert_val = str(row_vals[-1]) if row_vals else ""
            bg = ALERT_COLORS.get(alert_val, "EFF6FF" if ri%2==0 else "FFFFFF")
            fill = PatternFill("solid", fgColor=bg)
            for ci, val in enumerate(row_vals, 1):
                c = ws.cell(row=ri, column=ci, value=val)
                c.font      = XFont(name="Times New Roman", size=13)
                c.fill      = fill
                c.border    = BORDER
                c.alignment = Alignment(vertical="center",
                                        horizontal="center" if ci > 4 else "left")
            ws.row_dimensions[ri].height = 18

        # Auto-width cột
        for ci, col_name in enumerate(df_display.columns, 1):
            max_w = max(len(str(col_name)),
                        max((len(str(ws.cell(row=r, column=ci).value or ""))
                             for r in range(4, len(df_display)+5)), default=0))
            ws.column_dimensions[get_column_letter(ci)].width = min(max_w+3, 38)

        ws.freeze_panes = "A5"

        buf = BytesIO(); wb.save(buf); buf.seek(0)
        st.download_button(
            "⬇️ Tải báo cáo Excel (.xlsx)",
            data=buf.getvalue(),
            file_name=f"BaoCao_LichSu_ATTP_{now_vn().strftime('%d-%m-%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, type="primary",
        )
    except Exception as e:
        st.error(f"Lỗi xuất Excel: {e}")

    # ── Feedback Phụ Huynh ────────────────────────────────────────────────────
    if role in ("Ban Giám Hiệu", "Ban Giám Sát (Đại Diện PHHS)"):
        st.markdown('<div class="sf-div"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sec-hdr">📬 Feedback Phụ Huynh chưa xử lý</div>',
                    unsafe_allow_html=True)
        feedbacks = db_get_feedback(school=school_input.strip())
        if not feedbacks:
            st.info("Không có feedback mới từ Phụ Huynh.")
        else:
            for fb in feedbacks:
                col_fb, col_btn = st.columns([5, 1])
                col_fb.markdown(
                    f'<div class="sf-card" style="padding:10px 16px;margin:4px 0">'
                    f'<span style="font-size:0.75rem;color:#64748B">'
                    f'{fb.get("created_at","")[:10]} · {fb.get("category","")}</span><br>'
                    f'<span style="font-size:0.9rem;color:#1E293B">{fb.get("content","")}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
                if col_btn.button("✅ Đã xử lý", key=f"fb_{fb['id']}",
                                  use_container_width=True):
                    db_update_feedback_status(fb["id"], "resolved")
                    st.rerun()


def tab_supplier(api_key: str = ""):
    """G4: Checklist kiểm tra nhà cung cấp suất ăn 12 điểm."""
    st.markdown(
        '<div class="sf-card">'
        '<div class="sf-card-title">🏭 Kiểm tra Nhà Cung Cấp Suất Ăn</div>'
        '<div class="sf-card-body">'
        'Checklist 12 điểm · 6 mục bắt buộc (*) · '
        'Khi chấm <b>Không Đạt</b>: bắt buộc có ghi chú mô tả lỗi <i>hoặc</i> ảnh minh chứng · '
        'Tối đa 1 ảnh/mục (jpg, png, ≤5 MB) · AI Vision phân tích hình ảnh từng mục · '
        'Phải chấm đủ 12 mục mới được tạo báo cáo'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # ── Thông tin chung ────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    sup_school    = c1.text_input("🏫 Tên trường", placeholder="VD: TH Nguyễn Du",
                                   key="sup_school", max_chars=100)
    sup_name      = c2.text_input("🏭 Tên nhà cung cấp", placeholder="VD: Công ty TNHH Bếp Xanh",
                                   key="sup_name", max_chars=100)
    c3, c4 = st.columns(2)
    sup_inspector = c3.text_input("👤 Người kiểm tra", placeholder="Họ và tên",
                                   key="sup_inspector", max_chars=80)
    sup_date      = c4.date_input("📅 Ngày kiểm tra", value=now_vn().date(),
                                   key="sup_date", format="DD/MM/YYYY")
    sup_contract  = st.text_input("📃 Số hợp đồng cung cấp (nếu có)", placeholder="VD: HĐ-2025-001",
                                   key="sup_contract", max_chars=50)

    # Session state
    for _sk in ("sup_r", "sup_notes", "sup_imgs", "sup_vision"):
        if _sk not in st.session_state:
            st.session_state[_sk] = {}

    # ── Checklist 12 điểm ─────────────────────────────────────────────────────
    st.markdown('<div class="sec-hdr">📋 Checklist 12 điểm kiểm tra</div>', unsafe_allow_html=True)
    st.caption(
        "• Phải chấm đủ cả 12 mục (Đạt hoặc Không Đạt)  "
        "• Khi Không Đạt: bắt buộc điền Ghi chú ≥ 10 ký tự HOẶC tải ảnh minh chứng  "
        "• Tối đa 1 ảnh/mục · Ảnh được phân tích tự động bằng Claude Vision"
    )

    pass_count = fail_count = 0

    for item in SUPPLIER_ITEMS:
        code     = item["code"]
        is_crit  = item["critical"]

        # Đọc TRỰC TIẾP từ widget key → màu đổi ngay lần bấm đầu tiên (không lag)
        cur = st.session_state.get(f"sup_seg_{code}")
        is_fail   = (cur == "❌ Không Đạt")
        has_img   = code in st.session_state.sup_imgs
        has_note  = len(st.session_state.sup_notes.get(code, "").strip()) >= 10
        need_evid = is_fail and not has_img and not has_note

        # Màu theo trạng thái — giống hệt checklist tab
        if cur == "✅ Đạt":
            row_left = "#16A34A"; row_bg = "#F0FDF4"
            code_icon = "✅"
            state_lbl = '<span style="font-size:0.7rem;font-weight:700;color:#16A34A;margin-left:6px">ĐẠT</span>'
        elif cur == "❌ Không Đạt":
            row_left = "#F97316" if need_evid else "#DC2626"
            row_bg   = "#FFF7ED" if need_evid else "#FFF5F5"
            code_icon = "❌"
            state_lbl = '<span style="font-size:0.7rem;font-weight:700;color:#DC2626;margin-left:6px">KHÔNG ĐẠT</span>'
        else:  # None — chưa chọn
            row_left = "#F59E0B"; row_bg = "#FFFBEB"
            code_icon = "○"
            state_lbl = '<span style="font-size:0.7rem;color:#D97706;margin-left:6px">chưa chấm</span>'

        crit_badge = (
            '<span style="background:#FEE2E2;color:#991B1B;font-size:0.65rem;font-weight:700;'
            'padding:1px 6px;border-radius:8px;margin-left:6px;border:1px solid #FECACA">BẮT BUỘC</span>'
        ) if is_crit else ""

        col_desc, col_ctrl = st.columns([0.60, 0.40])

        with col_desc:
            st.markdown(
                f'<div style="background:{row_bg};border-left:3px solid {row_left};'
                f'border-radius:0 8px 8px 0;padding:10px 14px;margin:4px 0;'
                f'transition:background 0.4s ease,border-color 0.4s ease">'
                f'<div style="margin-bottom:4px;display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
                f'<span style="font-size:0.75rem;font-weight:800;color:{row_left}">'
                f'{code_icon} {code}</span>'
                f'{crit_badge}{state_lbl}'
                + (f'<span style="font-size:0.68rem;color:#EA580C;font-weight:600;margin-left:8px">'
                   f'⚠️ Cần bổ sung ghi chú/ảnh</span>' if need_evid else '')
                + f'</div>'
                f'<div style="font-size:0.87rem;font-weight:500;color:#1E293B;line-height:1.55">'
                f'{item["icon"]} {item["desc"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.expander("🔍 Hướng dẫn & tiêu chuẩn"):
                st.markdown(
                    f"**💡 Thực hiện:** {item['hint']}  \n"
                    f"**✅ Đạt khi:** {item['pass_std']}  \n"
                    f"**❌ Không đạt khi:** {item['fail_std']}  \n"
                    f"**📖 Căn cứ pháp lý:** {item['law']}"
                )

        with col_ctrl:
            st.segmented_control(
                label=code,
                options=["✅ Đạt", "❌ Không Đạt"],
                key=f"sup_seg_{code}",
                label_visibility="collapsed",
            )
            result = st.session_state.get(f"sup_seg_{code}")
            st.session_state.sup_r[code] = result

        if result == "✅ Đạt":
            pass_count += 1
        elif result == "❌ Không Đạt":
            fail_count += 1

        # Ghi chú — bắt buộc nếu Không Đạt và không có ảnh
        _note_req = (result == "❌ Không Đạt")
        _note_lbl = ("📝 Ghi chú mô tả lỗi — BẮT BUỘC nếu không có ảnh (≥ 10 ký tự)"
                     if _note_req else "📝 Ghi chú (tuỳ chọn)")
        note = st.text_area(
            _note_lbl, key=f"sup_note_{code}", max_chars=300, height=70,
            placeholder=(
                "Mô tả cụ thể lỗi quan sát được, ví dụ: Xe giao hàng không có thùng cách nhiệt, "
                "thùng chứa bám bẩn, nhiệt kế đo được 35°C..."
                if _note_req else "Ghi chú thêm nếu cần..."
            ),
        )
        st.session_state.sup_notes[code] = note

        # Upload ảnh — tối đa 1 ảnh/mục
        _img_lbl = (
            "📷 Ảnh minh chứng lỗi — BẮT BUỘC nếu không có ghi chú (1 ảnh · jpg/png · ≤ 5 MB)"
            if _note_req else "📷 Ảnh minh chứng (tuỳ chọn · 1 ảnh · jpg/png · ≤ 5 MB)"
        )
        uploaded = st.file_uploader(
            _img_lbl, type=["jpg", "jpeg", "png"],
            key=f"sup_img_{code}", accept_multiple_files=False,
        )
        if uploaded is not None:
            raw = uploaded.read()
            if len(raw) <= 5 * 1024 * 1024:
                st.session_state.sup_imgs[code] = {
                    "bytes": raw,
                    "type": uploaded.type or "image/jpeg",
                    "name": uploaded.name,
                }
            else:
                st.warning(f"[{code}] Ảnh vượt 5 MB — vui lòng chọn ảnh nhỏ hơn.")

        # Hiện ảnh + nút Vision nếu đã có ảnh
        if code in st.session_state.sup_imgs:
            _img_data = st.session_state.sup_imgs[code]
            _i1, _i2 = st.columns([1, 3])
            _i1.image(_img_data["bytes"], width=160, caption=f"Ảnh [{code}]")

            if api_key:
                if _i2.button(
                    f"🔍 Phân tích ảnh [{code}] với Claude Vision",
                    key=f"sup_vis_btn_{code}",
                ):
                    import base64 as _b64mod
                    _b64str = _b64mod.b64encode(_img_data["bytes"]).decode()
                    _mtype  = _img_data.get("type", "image/jpeg")
                    _vp = (
                        f"Đây là hình ảnh minh chứng kiểm tra mục [{code}]: \"{item['desc']}\" "
                        f"trong biên bản kiểm tra nhà cung cấp suất ăn học đường Việt Nam. "
                        f"Tiêu chuẩn ĐẠT: {item['pass_std']}. "
                        f"Tiêu chuẩn KHÔNG ĐẠT: {item['fail_std']}. "
                        f"Người kiểm tra chấm: {result}. "
                        f"Hãy quan sát hình ảnh và cho biết trong 2–3 câu ngắn gọn: "
                        f"hình ảnh thể hiện điều gì, có phù hợp với kết quả đã chấm không, "
                        f"và những gì cần ghi nhận. Viết bằng tiếng Việt."
                    )
                    try:
                        _client = anthropic.Anthropic(api_key=api_key)
                        with _i2:
                            with st.spinner("Claude Vision đang phân tích hình ảnh..."):
                                _vmsg = _client.messages.create(
                                    model=MODEL_VISION, max_tokens=350,
                                    messages=[{"role": "user", "content": [
                                        {"type": "image", "source": {
                                            "type": "base64",
                                            "media_type": _mtype,
                                            "data": _b64str,
                                        }},
                                        {"type": "text", "text": _vp},
                                    ]}],
                                )
                        _vtext = _vmsg.content[0].text if _vmsg.content else ""
                        st.session_state.sup_vision[code] = _vtext
                    except Exception as _ve:
                        _i2.error(f"Lỗi Vision [{code}]: {_ve}")

            if code in st.session_state.sup_vision:
                _i2.markdown(
                    f'<div style="background:#EEF2FF;border-left:3px solid #6366F1;'
                    f'border-radius:6px;padding:8px 12px;font-size:0.8rem;color:#3730A3;margin-top:6px">'
                    f'🤖 <b>Vision [{code}]:</b> {st.session_state.sup_vision[code]}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── KPI realtime ──────────────────────────────────────────────────────────
    _checked = pass_count + fail_count  # số mục đã chọn (không tính None)
    st.markdown("<br>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    pct = round(pass_count / max(_checked, 1) * 100) if _checked else 0
    crit_fails = [c for c, v in st.session_state.sup_r.items()
                  if v == "❌ Không Đạt" and c in SUPPLIER_CRITICAL]
    if _checked < len(SUPPLIER_ITEMS):
        alert_key, rating = "OK", "—"   # chưa chấm xong → chưa xếp loại
    elif crit_fails:
        alert_key, rating = "CRITICAL", "C"
    elif pass_count < SUPPLIER_SCORE_WARN:
        alert_key, rating = "MAJOR", "C"
    elif pass_count < SUPPLIER_SCORE_PASS:
        alert_key, rating = "MINOR", "B"
    else:
        alert_key, rating = "OK", "A"

    rating_color = {"A": "#16A34A", "B": "#F59E0B", "C": "#DC2626", "—": "#64748B"}[rating]

    m1.markdown(f'<div class="metric-box"><div class="metric-lbl">Đã kiểm tra</div>'
                f'<div class="metric-num c-blue">{_checked}</div>'
                f'<div class="metric-lbl">/ {len(SUPPLIER_ITEMS)} mục</div></div>',
                unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-box"><div class="metric-lbl">✅ Đạt</div>'
                f'<div class="metric-num c-green">{pass_count}</div>'
                f'<div class="metric-lbl">điểm</div></div>',
                unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-box"><div class="metric-lbl">❌ Không đạt</div>'
                f'<div class="metric-num c-red">{fail_count}</div>'
                f'<div class="metric-lbl">điểm</div></div>',
                unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-box"><div class="metric-lbl">Xếp loại</div>'
                f'<div class="metric-num" style="color:{rating_color};font-size:1.6rem;line-height:1.2">'
                f'Loại {rating}<br>'
                f'<span style="font-size:0.75rem;font-weight:600">{pct}% đạt</span></div></div>',
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # Banner cảnh báo
    if crit_fails:
        fail_descs = ['[' + c + '] ' + next(x["desc"] for x in SUPPLIER_ITEMS if x["code"] == c)
                      for c in crit_fails]
        st.markdown(
            '<div class="alert-critical">'
            '<div class="alert-title">🔴 VI PHẠM MỤC BẮT BUỘC (*) — BÁO BAN GIÁM HIỆU NGAY</div>'
            '<div class="alert-body">' + "<br>".join(f"• {d}" for d in fail_descs) + '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    elif alert_key == "MAJOR":
        st.markdown(
            '<div class="alert-major"><div class="alert-title">🟠 Nhà cung cấp CHƯA ĐẠT — '
            'Yêu cầu khắc phục trước bữa ăn tiếp theo</div></div>',
            unsafe_allow_html=True,
        )
    elif alert_key == "MINOR":
        st.markdown(
            '<div class="alert-minor"><div class="alert-title">🟡 Cần cải thiện — '
            'Thông báo nhà cung cấp trong 24 giờ</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="alert-ok"><div class="alert-title">✅ Nhà cung cấp ĐẠT chuẩn — '
            'Lưu hồ sơ và tiếp tục theo dõi</div></div>',
            unsafe_allow_html=True,
        )

    # ── AI Phân tích rủi ro tổng hợp ─────────────────────────────────────────
    st.markdown('<div class="sec-hdr">🤖 AI Phân tích rủi ro tổng hợp (Tuỳ chọn — chạy trước khi tạo báo cáo)</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="sf-card" style="border-left:3px solid #7C3AED;margin-bottom:10px">'
        '<div class="sf-card-title">Mục đích &amp; Cách đánh giá của AI</div>'
        '<div class="sf-card-body">'
        '<b>AI xem xét:</b> (1) Danh sách mục Không Đạt + ghi chú mô tả lỗi của người kiểm tra, '
        '(2) Nhận xét hình ảnh từ Claude Vision (nếu đã chạy từng mục). '
        '<br><b>AI đánh giá:</b> Mức độ rủi ro ngộ độc thực phẩm theo khung HACCP — '
        'Critical Control Point nào bị vi phạm, nguyên nhân có thể, mức độ nghiêm trọng. '
        '<br><b>AI đề xuất:</b> Biện pháp khắc phục cụ thể, có dẫn chiếu điều khoản Luật ATTP Việt Nam '
        '(NĐ 15/2018, QCVN 8-1:2011, TTLT 13/2016). '
        '<br><b>Kết quả AI được đính kèm vào báo cáo Word.</b>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    _ai_disabled = not api_key or fail_count == 0
    _ai_hint = ("Chỉ cần thiết khi có mục Không Đạt" if fail_count == 0
                else ("Cần nhập API key" if not api_key else f"Phân tích {fail_count} mục không đạt"))
    if st.button(f"🤖 Chạy phân tích AI ({_ai_hint})",
                 disabled=_ai_disabled, use_container_width=False):
        _fails = []
        for _it in SUPPLIER_ITEMS:
            _c = _it["code"]
            if st.session_state.sup_r.get(_c) == "❌ Không Đạt":
                _note_txt = st.session_state.sup_notes.get(_c, "").strip()
                _vision_txt = st.session_state.sup_vision.get(_c, "")
                _entry = f"[{_c}] {_it['desc']}"
                if _note_txt:
                    _entry += f" — Ghi chú: {_note_txt}"
                if _vision_txt:
                    _entry += f" — Vision AI nhận xét: {_vision_txt}"
                _fails.append(_entry)

        _prompt = (
            f"Đây là kết quả kiểm tra nhà cung cấp suất ăn học đường '{sup_name}' "
            f"tại trường '{sup_school}' ngày {sup_date.strftime('%d/%m/%Y')}. "
            f"Xếp loại: {rating} ({pct}% đạt — {pass_count}/{len(SUPPLIER_ITEMS)} điểm). "
            f"Các vi phạm phát hiện:\n" + "\n".join(f"  {x}" for x in _fails) + "\n\n"
            "Hãy viết phân tích ngắn gọn (khoảng 200 từ) bằng tiếng Việt bao gồm:\n"
            "1. Đánh giá mức độ rủi ro ngộ độc thực phẩm theo HACCP (CCP nào bị vi phạm)\n"
            "2. Nguyên nhân có thể và hậu quả tiềm ẩn\n"
            "3. Biện pháp khắc phục ưu tiên, dẫn chiếu điều khoản pháp luật cụ thể\n"
            "4. Khuyến nghị hành động tiếp theo (tạm dừng / tiếp tục / tăng tần suất giám sát)"
        )
        try:
            _client = anthropic.Anthropic(api_key=api_key)
            with st.spinner("AI đang phân tích toàn bộ kết quả kiểm tra..."):
                _amsg = _client.messages.create(
                    model=MODEL, max_tokens=800,
                    messages=[{"role": "user", "content": _prompt}],
                )
            _ai_text = _amsg.content[0].text if _amsg.content else ""
            st.session_state["sup_ai_analysis"] = _ai_text
            st.markdown(
                '<div class="sf-card" style="border-left:3px solid #7C3AED">'
                '<div class="sf-card-title">🤖 Kết quả phân tích AI tổng hợp</div>'
                f'<div class="sf-card-body">{_ai_text}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        except Exception as _ae:
            st.error(f"Lỗi AI: {_ae}")

    if "sup_ai_analysis" in st.session_state and st.session_state.sup_ai_analysis:
        st.caption("✅ Kết quả AI đã được lưu — sẽ được đính kèm vào báo cáo Word khi tạo.")

    # ── Validate ─────────────────────────────────────────────────────────────
    # Mục chưa chọn (None = chưa chấm)
    _unselected = [item["code"] for item in SUPPLIER_ITEMS
                   if st.session_state.sup_r.get(item["code"]) is None]
    # Mục Không Đạt thiếu bằng chứng
    _missing_evid = [
        item["code"] for item in SUPPLIER_ITEMS
        if st.session_state.sup_r.get(item["code"]) == "❌ Không Đạt"
        and item["code"] not in st.session_state.sup_imgs
        and len(st.session_state.sup_notes.get(item["code"], "").strip()) < 10
    ]
    can_submit = (
        bool(sup_school.strip()) and
        bool(sup_name.strip()) and
        bool(sup_inspector.strip()) and
        len(_unselected) == 0 and
        len(_missing_evid) == 0
    )

    # ── Tạo báo cáo Word + lưu DB ─────────────────────────────────────────────
    st.markdown('<div class="sec-hdr">📄 Tạo báo cáo & Lưu hồ sơ</div>', unsafe_allow_html=True)

    if not can_submit:
        _miss = []
        if not sup_school.strip():    _miss.append("Tên trường")
        if not sup_name.strip():      _miss.append("Tên nhà cung cấp")
        if not sup_inspector.strip(): _miss.append("Người kiểm tra")
        if _unselected:
            _miss.append(f"Chưa chấm {len(_unselected)} mục: {', '.join(_unselected)}")
        if _missing_evid:
            _miss.append(f"Mục Không Đạt chưa có ghi chú/ảnh: {', '.join(_missing_evid)}")
        st.warning("⚠️ Chưa đủ điều kiện tạo báo cáo: " + " · ".join(_miss))

    if st.button("📄 Tạo báo cáo Word & Lưu DB", type="primary",
                 disabled=not can_submit, use_container_width=True):
        guard_key = f"sup_saved_{sup_school}_{sup_date}_{sup_inspector}"
        already_saved = st.session_state.get(guard_key, False)

        ai_narrative = st.session_state.get("sup_ai_analysis", f"Xếp loại {rating}")

        # Lưu DB (chỉ 1 lần)
        if not already_saved and db_ok():
            _res_dict = {}
            for _it in SUPPLIER_ITEMS:
                _c = _it["code"]
                _v = st.session_state.sup_r.get(_c, "")
                _res_dict[_c] = "Đạt" if _v == "✅ Đạt" else "Không Đạt"
            _notes_dict = {c: st.session_state.sup_notes.get(c, "") for c in _res_dict}
            _sid = db_save_checklist(
                school=sup_school, date_str=str(sup_date),
                inspector=sup_inspector, menu=f"NCC: {sup_name}",
                level="—", results=_res_dict, notes=_notes_dict,
                alert_level=alert_key, pass_count=pass_count, fail_count=fail_count,
                ai_narrative=ai_narrative[:500],
                extra_results={"contract": sup_contract, "supplier": sup_name},
            )
            if _sid:
                st.session_state[guard_key] = True
                st.success("✅ Đã lưu vào database!")
            else:
                st.warning("Không lưu được DB — kiểm tra kết nối Supabase.")
        elif already_saved:
            st.info("Phiên này đã lưu DB — chỉ xuất lại file Word.")
        else:
            st.warning("Database chưa kết nối — chỉ tạo file Word, không lưu DB.")

        # Tạo Word
        try:
            from docx import Document
            from docx.shared import Pt, Cm, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from io import BytesIO

            doc = Document()
            _sty = doc.styles["Normal"]
            _sty.font.name = "Times New Roman"
            _sty.font.size = Pt(13)
            for _sec in doc.sections:
                _sec.top_margin    = Cm(2.5); _sec.bottom_margin = Cm(2.5)
                _sec.left_margin   = Cm(3.0); _sec.right_margin  = Cm(2.0)

            def _wr(para, text, bold=False, size=13, color=None):
                r = para.add_run(text)
                r.font.name = "Times New Roman"; r.font.size = Pt(size); r.bold = bold
                if color: r.font.color.rgb = color
                return r

            # Quốc hiệu
            for _txt in ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", "Độc lập – Tự do – Hạnh phúc"):
                _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _wr(_p, _txt, bold=True)

            doc.add_paragraph("")
            _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _wr(_p, "BIÊN BẢN KIỂM TRA NHÀ CUNG CẤP SUẤT ĂN HỌC ĐƯỜNG", bold=True, size=14)

            _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _wr(_p, f"Ngày {sup_date.strftime('%d/%m/%Y')} · NCC: {sup_name} · Trường: {sup_school}")

            doc.add_paragraph("")
            for _lbl, _val in [
                ("Tên trường", sup_school), ("Nhà cung cấp", sup_name),
                ("Người kiểm tra", sup_inspector), ("Ngày kiểm tra", sup_date.strftime("%d/%m/%Y")),
                ("Số hợp đồng", sup_contract or "—"),
                ("Kết quả tổng hợp", f"Loại {rating} — {pct}% đạt ({pass_count}/{len(SUPPLIER_ITEMS)} điểm)"),
            ]:
                _p = doc.add_paragraph()
                _wr(_p, f"{_lbl}: ", bold=True)
                _wr(_p, _val)

            doc.add_paragraph("")
            _p = doc.add_paragraph(); _wr(_p, "KẾT QUẢ KIỂM TRA CHI TIẾT (12 ĐIỂM)", bold=True)

            # Bảng 5 cột
            _tbl = doc.add_table(rows=1, cols=5)
            _tbl.style = "Table Grid"
            _hdrs = ["Mã", "Nội dung kiểm tra", "Kết quả", "Ghi chú", "Vision AI"]
            for _ci, _h in enumerate(_hdrs):
                _tbl.rows[0].cells[_ci].text = _h
                for _pp in _tbl.rows[0].cells[_ci].paragraphs:
                    for _rr in _pp.runs:
                        _rr.bold = True
                        _rr.font.name = "Times New Roman"; _rr.font.size = Pt(11)

            for _it in SUPPLIER_ITEMS:
                _c = _it["code"]
                _row = _tbl.add_row().cells
                _row[0].text = f"{_c}{'(*)' if _it['critical'] else ''}"
                _row[1].text = _it["desc"]
                _rv = st.session_state.sup_r.get(_c, "")
                _row[2].text = "Đạt" if _rv == "✅ Đạt" else "Không Đạt"
                _row[3].text = st.session_state.sup_notes.get(_c, "")
                _row[4].text = st.session_state.sup_vision.get(_c, "")
                if _row[2].text == "Không Đạt":
                    for _pp in _row[2].paragraphs:
                        for _rr in _pp.runs:
                            _rr.font.color.rgb = RGBColor(0xDC, 0x26, 0x26)
                for _cell in _row:
                    for _pp in _cell.paragraphs:
                        for _rr in _pp.runs:
                            _rr.font.name = "Times New Roman"; _rr.font.size = Pt(11)

            # Ảnh minh chứng trong Word (embed nếu có)
            _img_count = sum(1 for c in st.session_state.sup_imgs
                             if st.session_state.sup_r.get(c) == "❌ Không Đạt")
            if _img_count > 0:
                doc.add_paragraph("")
                _p = doc.add_paragraph(); _wr(_p, "ẢNH MINH CHỨNG CÁC MỤC KHÔNG ĐẠT", bold=True)
                for _it2 in SUPPLIER_ITEMS:
                    _c2 = _it2["code"]
                    if (_c2 in st.session_state.sup_imgs and
                            st.session_state.sup_r.get(_c2) == "❌ Không Đạt"):
                        _p2 = doc.add_paragraph()
                        _wr(_p2, f"[{_c2}] {_it2['desc']}", bold=True, size=11)
                        try:
                            from io import BytesIO as _BIO
                            _ibuf = _BIO(st.session_state.sup_imgs[_c2]["bytes"])
                            doc.add_picture(_ibuf, width=Cm(10))
                        except Exception:
                            _p3 = doc.add_paragraph()
                            _wr(_p3, "(Không nhúng được ảnh — xem ảnh trong hồ sơ digital)", size=11)

            # Kết luận
            doc.add_paragraph("")
            _concl = {
                "A": f"Nhà cung cấp {sup_name} ĐẠT chuẩn (Loại A). Tiếp tục hợp đồng bình thường.",
                "B": f"Nhà cung cấp {sup_name} xếp Loại B. Thông báo khắc phục trong 24 giờ.",
                "C": f"Nhà cung cấp {sup_name} KHÔNG ĐẠT (Loại C). Báo Ban Giám Hiệu ngay. "
                     f"Xem xét tạm dừng hợp đồng.",
            }[rating]
            _p = doc.add_paragraph(); _wr(_p, "KẾT LUẬN: ", bold=True)
            _wr(_p, _concl)
            if crit_fails:
                _wr(_p, f"\n⚠️ Vi phạm mục bắt buộc: {', '.join(crit_fails)}",
                    color=RGBColor(0xDC, 0x26, 0x26))

            # AI analysis trong Word
            if ai_narrative and "Xếp loại" not in ai_narrative:
                doc.add_paragraph("")
                _p = doc.add_paragraph(); _wr(_p, "PHÂN TÍCH RỦI RO (AI):", bold=True)
                _p2 = doc.add_paragraph(); _wr(_p2, ai_narrative, size=12)

            # Chữ ký
            doc.add_paragraph("")
            _p = doc.add_paragraph(
                f"......., ngày {sup_date.strftime('%d')} tháng "
                f"{sup_date.strftime('%m')} năm {sup_date.strftime('%Y')}"
            )
            _p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for _rr in _p.runs: _rr.font.name = "Times New Roman"; _rr.font.size = Pt(13)

            _sig_tbl = doc.add_table(rows=1, cols=2)
            _s1, _s2 = _sig_tbl.rows[0].cells
            _s1.text = "NGƯỜI KIỂM TRA\n(Ký, ghi rõ họ tên)"
            _s2.text = "ĐẠI DIỆN NHÀ CUNG CẤP\n(Ký, ghi rõ họ tên)"
            for _cell in [_s1, _s2]:
                for _pp in _cell.paragraphs:
                    _pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    for _rr in _pp.runs:
                        _rr.bold = True
                        _rr.font.name = "Times New Roman"; _rr.font.size = Pt(13)

            _buf = BytesIO()
            doc.save(_buf); _buf.seek(0)
            _fn = f"KiemTraNCC_{sup_name.replace(' ', '_')}_{sup_date.strftime('%Y%m%d')}.docx"
            st.download_button(
                "⬇️ Tải báo cáo Word (.docx)", data=_buf.getvalue(), file_name=_fn,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as _we:
            st.error(f"Lỗi tạo Word: {_we}")


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
                       layout="wide", initial_sidebar_state="collapsed")
    inject_css()

    # Header chính — không dùng HTML comments để tránh Streamlit hiển thị raw text
    _circles = (
        '<div style="position:absolute;top:-40px;right:-40px;width:220px;height:220px;'
        'border-radius:50%;background:rgba(255,255,255,0.05);pointer-events:none"></div>'
        '<div style="position:absolute;bottom:-60px;right:80px;width:160px;height:160px;'
        'border-radius:50%;background:rgba(255,255,255,0.04);pointer-events:none"></div>'
    )
    _badges = (
        '<span style="background:rgba(255,255,255,0.15);color:white;padding:4px 12px;'
        'border-radius:20px;font-size:0.75rem;font-weight:600;border:1px solid rgba(255,255,255,0.2)">'
        '⚖️ NĐ 15/2018</span>'
        '<span style="background:rgba(255,255,255,0.15);color:white;padding:4px 12px;'
        'border-radius:20px;font-size:0.75rem;font-weight:600;border:1px solid rgba(255,255,255,0.2)">'
        '🤖 AI Vision</span>'
        '<span style="background:rgba(34,197,94,0.25);color:#86EFAC;padding:4px 12px;'
        'border-radius:20px;font-size:0.75rem;font-weight:600;border:1px solid rgba(134,239,172,0.3)">'
        '🟢 Live</span>'
    )
    _stat = lambda val, lbl, clr: (
        f'<div style="flex:1;min-width:80px;text-align:center;padding:0 8px">'
        f'<div style="color:{clr};font-size:1.8rem;font-weight:800;line-height:1.1">{val}</div>'
        f'<div style="color:#BFDBFE;font-size:0.82rem;margin-top:5px;font-weight:500">{lbl}</div></div>'
    )
    _sep = '<div style="width:1px;background:rgba(255,255,255,0.15);margin:0 2px"></div>'
    _stats = (
        _stat("20", "Điểm kiểm tra", "white") + _sep +
        _stat("7",  "Mục bắt buộc",  "#FCA5A5") + _sep +
        _stat("4",  "Cấp cảnh báo",  "#6EE7B7") + _sep +
        _stat("6",  "Văn bản pháp lý","#FDE68A") + _sep +
        _stat("🤖", "AI phân tích",   "#C4B5FD")
    )
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0F2651 0%,#1B3B6F 45%,#1D4ED8 100%);'
        f'border-radius:16px;padding:28px 32px 22px 32px;margin-bottom:14px;'
        f'position:relative;overflow:hidden;box-shadow:0 8px 32px rgba(15,38,81,0.25)">'
        f'{_circles}'
        f'<div style="display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap">'
        f'<div style="display:flex;align-items:center;gap:14px;flex:1;min-width:200px">'
        f'<span style="font-size:2.6rem;line-height:1">🍱</span>'
        f'<div><div style="color:white;font-size:1.9rem;font-weight:800;letter-spacing:-0.5px;line-height:1.1">'
        f'SchoolFood AI</div>'
        f'<div style="color:#93C5FD;font-size:0.78rem;margin-top:4px;font-weight:500">'
        f'Phiên bản 2.0 &nbsp;·&nbsp; Cập nhật 06/2026</div></div></div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;padding-top:4px">{_badges}</div></div>'
        f'<p style="color:#DBEAFE;font-size:1.0rem;margin:14px 0 16px 0;line-height:1.65;font-weight:400">'
        f'Giám sát An toàn Thực phẩm bữa ăn học đường — dành cho '
        f'<b style="color:white">Phụ Huynh · Ban Giám Sát · Y Tế Học Đường · Ban Giám Hiệu</b></p>'
        f'<div style="display:flex;gap:0;border-top:1px solid rgba(255,255,255,0.15);'
        f'padding-top:14px;flex-wrap:wrap">{_stats}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Đọc API key (Secrets → ENV → trống) ─────────────────────────────────
    import os
    api_key = (
        (st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )

    # ── Thanh điều khiển ngang — thay thế sidebar, luôn hiển thị ─────────────
    st.markdown("""
    <div style="background:white;border:1px solid #E2E8F0;border-radius:12px;
                padding:12px 20px;margin-bottom:10px;
                box-shadow:0 1px 4px rgba(0,0,0,0.07)">
        <div style="font-size:0.72rem;font-weight:700;color:#94A3B8;
                    text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">
            ⚙️ Cài đặt người dùng
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Hàng 1: Vai trò / Cấp trường / Tỉnh TP / API status ─────────────────
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 1.5, 2.5])
    with ctrl1:
        role = st.selectbox(
            "Vai trò",
            ["Phụ Huynh", "Ban Giám Sát (Đại Diện PHHS)",
             "Y Tế Học Đường", "Ban Giám Hiệu"],
        )
    with ctrl2:
        level = st.selectbox(
            "Cấp trường",
            ["Tiểu Học (6–11 tuổi)", "THCS (12–15 tuổi)", "THPT (16–18 tuổi)"],
        )
    with ctrl3:
        loc = st.text_input("Tỉnh/TP", value="TP.HCM")
    with ctrl4:
        if api_key:
            # Dùng disabled input — tự động căn thẳng hàng với các Streamlit input khác
            st.text_input(
                "Trạng thái AI",
                value="✅ AI đã kết nối — sẵn sàng",
                disabled=True,
                label_visibility="visible",
            )
        else:
            manual_key = st.text_input(
                "Claude API Key (tuỳ chọn)",
                type="password",
                placeholder="sk-ant-...",
                help="Không có key? Checklist vẫn dùng được đầy đủ",
            )
            if manual_key:
                api_key = manual_key

    # ── Hàng 2: Mô tả vai trò + lịch nhắc nhở + hotline ─────────────────────
    DESCS = {
        "Phụ Huynh":                    "Xem thực đơn, kết quả kiểm tra và gửi phản hồi",
        "Ban Giám Sát (Đại Diện PHHS)": "Kiểm tra bếp ăn 2 lần/tuần, tạo báo cáo chính thức theo luật",
        "Y Tế Học Đường":               "Ghi kiểm thực 3 bước hàng ngày, xác nhận mẫu lưu thức ăn",
        "Ban Giám Hiệu":                "Xem tổng quan tình hình ATTP, duyệt báo cáo và quản lý nhà cung cấp",
    }
    ROLE_CLR = {
        "Phụ Huynh": "#2563EB", "Ban Giám Sát (Đại Diện PHHS)": "#7C3AED",
        "Y Tế Học Đường": "#0D9488", "Ban Giám Hiệu": "#B45309",
    }

    # Tính nhắc nhở
    _t_info   = _REMINDER_TIMES.get(role)
    _now      = now_vn()
    _reminder_txt = ""
    if _t_info and _now.weekday() < 5:
        _it     = _t_info["hour"] * 60 + _t_info["min"]
        _ct     = _now.hour * 60 + _now.minute
        _ml     = _it - _ct
        _is_day = _now.weekday() in _t_info["days"]
        if _is_day and 0 <= _ml <= 15:
            _reminder_txt = (
                f'&nbsp;&nbsp;<span style="background:#FEF9C3;color:#92400E;font-weight:700;'
                f'padding:2px 10px;border-radius:12px;font-size:0.78rem">'
                f'⏰ NHẮC: Còn {_ml} phút đến giờ kiểm tra!</span>'
            )
        elif _is_day and _ml > 0:
            _rt  = _it - 15
            _reminder_txt = (
                f'&nbsp;&nbsp;<span style="color:#64748B;font-size:0.78rem">'
                f'⏰ Nhắc nhở lúc {_rt//60:02d}:{_rt%60:02d} — Kiểm tra {_t_info["hour"]:02d}:{_t_info["min"]:02d}</span>'
            )
        elif _is_day and _ml <= 0:
            _reminder_txt = (
                f'&nbsp;&nbsp;<span style="color:#94A3B8;font-size:0.78rem">'
                f'Đã qua giờ kiểm tra hôm nay</span>'
            )
        elif not _is_day:
            _next_d = next((d for d in sorted(_t_info["days"]) if d > _now.weekday()), min(_t_info["days"]))
            _day_vn = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6"][_next_d]
            _reminder_txt = (
                f'&nbsp;&nbsp;<span style="color:#64748B;font-size:0.78rem">'
                f'📅 Lịch tiếp theo: {_day_vn} {_t_info["hour"]:02d}:{_t_info["min"]:02d}</span>'
            )

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'font-size:0.82rem;color:#475569;margin-bottom:6px;flex-wrap:wrap;gap:4px">'
        f'<span><b style="color:{ROLE_CLR.get(role,"#64748B")}">{role}:</b> '
        f'{DESCS.get(role,"")}{_reminder_txt}</span>'
        f'<span style="color:#94A3B8">🔴 Khẩn cấp: <b>115</b> &nbsp;·&nbsp; Cục ATTP: <b>1800 6838</b></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Hiển thị banner nhắc nhở nổi bật nếu trong 15 phút
    show_reminder_banner(role)

    # Nhãn tab thay đổi theo vai trò
    _tab2_labels = {
        "Phụ Huynh":                    "👨‍👩‍👧 Góc Phụ Huynh",
        "Y Tế Học Đường":               "🏥 Kiểm thực 3 bước",
        "Ban Giám Sát (Đại Diện PHHS)": "✅ Checklist kiểm tra",
        "Ban Giám Hiệu":                "✅ Checklist kiểm tra",
    }
    tab2_label = _tab2_labels.get(role, "✅ Checklist kiểm tra")

    # Hiện tab Lịch sử khi có DB (hoặc luôn hiện để hướng dẫn setup)
    _hist_label = "📊 Lịch sử" + (" 🔴" if db_ok() and
        any(s.get("alert_level")=="CRITICAL"
            for s in db_get_sessions(limit=5)) else "")

    # Tab Nhà Cung Cấp chỉ dành cho Ban Giám Sát và Ban Giám Hiệu
    _show_supplier = role in ("Ban Giám Sát (Đại Diện PHHS)", "Ban Giám Hiệu")
    _tab_labels = [
        "💬 Hỏi đáp AI",
        tab2_label,
        _hist_label,
        "📅 Lịch & thông báo",
        "🚨 Khẩn cấp",
        "📖 Hướng dẫn",
        "ℹ️ Về ứng dụng",
    ]
    if _show_supplier:
        _tab_labels.insert(3, "🏭 Nhà Cung Cấp")

    _tabs = st.tabs(_tab_labels)
    t1, t2, t3 = _tabs[0], _tabs[1], _tabs[2]
    if _show_supplier:
        t_sup, t4, t5, t6, t7 = _tabs[3], _tabs[4], _tabs[5], _tabs[6], _tabs[7]
    else:
        t4, t5, t6, t7 = _tabs[3], _tabs[4], _tabs[5], _tabs[6]

    with t1: tab_chat(api_key, role, level, loc)
    with t2:
        if role == "Phụ Huynh":
            tab_parent_view(api_key)
        elif role == "Y Tế Học Đường":
            tab_kiem_thuc(api_key, level)
        else:
            tab_checklist(api_key)
    with t3: tab_history(role=role)
    if _show_supplier:
        with t_sup: tab_supplier(api_key)
    with t4: tab_schedule()
    with t5: tab_emergency(api_key)
    with t6: tab_guide()
    with t7: tab_about()


if __name__ == "__main__":
    main()
