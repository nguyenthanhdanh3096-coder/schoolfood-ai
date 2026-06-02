-- ============================================================
-- SCHOOLFOOD AI — Supabase Schema
-- Chạy toàn bộ file này trong Supabase SQL Editor
-- supabase.com → Project → SQL Editor → New query → Paste → Run
-- ============================================================

-- Bật extension UUID
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- BẢNG 1: Phiên kiểm tra (mỗi lần bấm "Tạo báo cáo")
-- ============================================================
CREATE TABLE IF NOT EXISTS checklist_sessions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name     TEXT        NOT NULL,
    inspector_name  TEXT,
    check_date      DATE        NOT NULL,
    menu_today      TEXT,
    school_level    TEXT,
    check_type      TEXT        DEFAULT 'ban_giam_sat',
    -- 'ban_giam_sat' | 'kiem_thuc_3_buoc' | 'nha_cung_cap'
    alert_level     TEXT,
    -- 'OK' | 'MINOR' | 'MAJOR' | 'CRITICAL'
    total_items     INTEGER,
    pass_count      INTEGER,
    fail_count      INTEGER,
    ai_narrative    TEXT,       -- Tóm tắt AI nếu có
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- BẢNG 2: Kết quả từng điểm kiểm tra
-- ============================================================
CREATE TABLE IF NOT EXISTS checklist_results (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID    REFERENCES checklist_sessions(id) ON DELETE CASCADE,
    item_code   TEXT    NOT NULL,       -- 'C01', 'B1_01', 'E01', 'S01'...
    item_desc   TEXT,
    result      TEXT,                   -- 'Đạt' | 'Không Đạt' | 'Chưa chấm'
    note        TEXT,
    is_critical BOOLEAN DEFAULT false,
    ai_analysis JSONB                   -- Kết quả Claude Vision nếu có
);

-- ============================================================
-- BẢNG 3: Timestamp kiểm thực 3 bước (Y Tế Học Đường)
-- ============================================================
CREATE TABLE IF NOT EXISTS kiem_thuc_steps (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID    REFERENCES checklist_sessions(id) ON DELETE CASCADE,
    step_no      INTEGER NOT NULL,      -- 1, 2, 3
    time_window  TEXT,                  -- '8:00 – 9:30'
    confirmed_at TEXT,                  -- 'HH:MM:SS'
    on_time      BOOLEAN,
    pass_count   INTEGER DEFAULT 0,
    fail_count   INTEGER DEFAULT 0
);

-- ============================================================
-- BẢNG 4: Feedback từ Phụ Huynh
-- ============================================================
CREATE TABLE IF NOT EXISTS parent_feedback (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name TEXT    NOT NULL,
    category    TEXT,
    content     TEXT    NOT NULL,
    status      TEXT    DEFAULT 'pending',
    -- 'pending' | 'reviewed' | 'resolved'
    reviewed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- BẢNG 5: Nhà cung cấp suất ăn (Phase G4)
-- ============================================================
CREATE TABLE IF NOT EXISTS suppliers (
    id             UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name    TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    license_no     TEXT,
    license_expiry DATE,
    phone          TEXT,
    address        TEXT,
    status         TEXT    DEFAULT 'active',
    risk_score     INTEGER DEFAULT 100,  -- 0-100, cao = tốt
    last_audit     DATE,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- INDEXES (tăng tốc truy vấn)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_sessions_school
    ON checklist_sessions(school_name, check_date DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_date
    ON checklist_sessions(check_date DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_school
    ON parent_feedback(school_name, status, created_at DESC);

-- ============================================================
-- VIEWS (tiện lợi cho dashboard)
-- ============================================================

-- View: thống kê theo trường
CREATE OR REPLACE VIEW school_stats AS
SELECT
    school_name,
    COUNT(*)                            AS total_sessions,
    ROUND(AVG(pass_count::float / NULLIF(total_items, 0) * 100), 1)
                                        AS avg_pass_rate,
    SUM(CASE WHEN alert_level = 'CRITICAL' THEN 1 ELSE 0 END)
                                        AS critical_count,
    MAX(check_date)                     AS last_check_date
FROM checklist_sessions
GROUP BY school_name;

-- View: feedback chưa xử lý
CREATE OR REPLACE VIEW pending_feedback AS
SELECT * FROM parent_feedback
WHERE status = 'pending'
ORDER BY created_at DESC;

-- ============================================================
-- KIỂM TRA: Chạy sau khi setup xong
-- ============================================================
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' ORDER BY table_name;
