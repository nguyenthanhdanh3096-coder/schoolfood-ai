-- ============================================================
-- SCHOOLFOOD AI — Supabase Schema v2.2
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
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name     TEXT        NOT NULL,
    category        TEXT,
    content         TEXT        NOT NULL,
    status          TEXT        DEFAULT 'pending',
    -- 'pending' | 'reviewed' | 'resolved'
    submitted_by    TEXT        DEFAULT '',   -- user_id từ user_profiles (nếu đăng nhập)
    evidence_text   TEXT        DEFAULT '',   -- BGS/Y Tế thêm minh chứng
    evidence_by     TEXT        DEFAULT '',   -- Tên người thêm minh chứng
    response_text   TEXT        DEFAULT '',   -- BGH phản hồi
    response_by     TEXT        DEFAULT '',   -- Tên BGH xử lý
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- BẢNG 5: Nhà cung cấp suất ăn — Registry chính thức
-- ============================================================
CREATE TABLE IF NOT EXISTS ncc_registry (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name     TEXT        NOT NULL,
    ncc_name        TEXT        NOT NULL,
    license_no      TEXT        DEFAULT '',   -- Số giấy phép CSSX
    license_expiry  DATE,                     -- Hết hạn giấy phép
    attp_expiry     DATE,                     -- Hết hạn chứng nhận ATTP
    phone           TEXT        DEFAULT '',
    address         TEXT        DEFAULT '',
    contract_no     TEXT        DEFAULT '',   -- Số hợp đồng
    notes           TEXT        DEFAULT '',
    cert_files      JSONB       DEFAULT '{}', -- {s01: url, s02: url, ...}
    is_active       BOOLEAN     DEFAULT true,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- BẢNG 6: Hồ sơ người dùng (G3 — Authentication)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    id              TEXT        PRIMARY KEY,   -- Supabase Auth user ID
    email           TEXT        UNIQUE NOT NULL,
    full_name       TEXT        NOT NULL,
    role            TEXT        NOT NULL DEFAULT 'phu_huynh',
    -- 'phu_huynh' | 'ban_giam_sat' | 'y_te_hoc_duong' | 'ban_giam_hieu'
    school_name     TEXT        DEFAULT '',
    default_level   TEXT        DEFAULT 'Tiểu Học (6–11 tuổi)',  -- Y Tế đa cấp
    zalo_user_id    TEXT        DEFAULT '',   -- Zalo OA User ID để gửi notification
    is_active       BOOLEAN     DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login      TIMESTAMPTZ,
    CONSTRAINT valid_role CHECK (
        role IN ('phu_huynh','ban_giam_sat','y_te_hoc_duong','ban_giam_hieu')
    )
);

-- ============================================================
-- MIGRATIONS — Chạy nếu database đã tồn tại (idempotent)
-- ============================================================

-- user_profiles: thêm columns mới
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS default_level  TEXT DEFAULT 'Tiểu Học (6–11 tuổi)';
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS zalo_user_id   TEXT DEFAULT '';

-- parent_feedback: thêm columns xử lý complaint
ALTER TABLE parent_feedback ADD COLUMN IF NOT EXISTS submitted_by  TEXT DEFAULT '';
ALTER TABLE parent_feedback ADD COLUMN IF NOT EXISTS evidence_text TEXT DEFAULT '';
ALTER TABLE parent_feedback ADD COLUMN IF NOT EXISTS evidence_by   TEXT DEFAULT '';
ALTER TABLE parent_feedback ADD COLUMN IF NOT EXISTS response_text TEXT DEFAULT '';
ALTER TABLE parent_feedback ADD COLUMN IF NOT EXISTS response_by   TEXT DEFAULT '';

-- ============================================================
-- INDEXES (tăng tốc truy vấn)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_sessions_school
    ON checklist_sessions(school_name, check_date DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_date
    ON checklist_sessions(check_date DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_school
    ON parent_feedback(school_name, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_profiles_school
    ON user_profiles(school_name);

CREATE INDEX IF NOT EXISTS idx_profiles_school_role
    ON user_profiles(school_name, role);

CREATE INDEX IF NOT EXISTS idx_ncc_school
    ON ncc_registry(school_name, is_active);

-- ============================================================
-- VIEWS (tiện lợi cho dashboard)
-- ============================================================

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

CREATE OR REPLACE VIEW pending_feedback AS
SELECT * FROM parent_feedback
WHERE status = 'pending'
ORDER BY created_at DESC;

-- ============================================================
-- SETUP: Tạo tài khoản Ban Giám Hiệu đầu tiên
-- ============================================================
-- 1. Vào Supabase → Authentication → Users → "Add user"
-- 2. Nhập email + mật khẩu → lấy User UID
-- 3. Chạy câu lệnh này (thay YOUR_USER_ID và YOUR_SCHOOL):
--
-- INSERT INTO user_profiles (id, email, full_name, role, school_name)
-- VALUES ('YOUR_USER_ID', 'admin@truong.edu.vn', 'Hiệu Trưởng', 'ban_giam_hieu', 'Trường XYZ')
-- ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- KIỂM TRA: Chạy sau khi setup xong
-- ============================================================
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' ORDER BY table_name;
--
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'user_profiles' ORDER BY ordinal_position;
