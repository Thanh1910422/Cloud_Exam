
-- ==================================================
-- HSK EXAM - DATABASE
-- PostgreSQL / Supabase
-- ==================================================

-- 1. ROLES: Phân quyền người dùng
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    role_name VARCHAR(30) UNIQUE NOT NULL
);

INSERT INTO roles (role_name)
VALUES
    ('admin'),
    ('teacher'),
    ('student')
ON CONFLICT (role_name) DO NOTHING;


-- 2. USERS: Tài khoản
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- 3. HSK LEVELS: Cấp độ HSK
CREATE TABLE IF NOT EXISTS hsk_levels (
    id SERIAL PRIMARY KEY,
    level_number INTEGER UNIQUE NOT NULL
        CHECK (level_number BETWEEN 1 AND 6),
    level_name VARCHAR(50) NOT NULL
);

INSERT INTO hsk_levels (level_number, level_name)
VALUES
    (1, 'HSK 1'),
    (2, 'HSK 2'),
    (3, 'HSK 3'),
    (4, 'HSK 4'),
    (5, 'HSK 5'),
    (6, 'HSK 6')
ON CONFLICT (level_number) DO NOTHING;


-- 4. EXAMS: Đề thi
CREATE TABLE IF NOT EXISTS exams (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    level_id INTEGER NOT NULL REFERENCES hsk_levels(id),
    teacher_id BIGINT REFERENCES users(id),
    duration_minutes INTEGER NOT NULL
        CHECK (duration_minutes > 0),
    status VARCHAR(20) DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'archived')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- 5. EXAM SECTIONS: Các phần thi
CREATE TABLE IF NOT EXISTS exam_sections (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id)
        ON DELETE CASCADE,
    section_type VARCHAR(20) NOT NULL
        CHECK (section_type IN ('listening', 'reading', 'writing')),
    section_title VARCHAR(150) NOT NULL,
    time_limit_minutes INTEGER,
    sort_order INTEGER DEFAULT 1,
    UNIQUE(exam_id, section_type)
);


-- 6. QUESTIONS: Câu hỏi
CREATE TABLE IF NOT EXISTS questions (
    id BIGSERIAL PRIMARY KEY,
    section_id BIGINT NOT NULL REFERENCES exam_sections(id)
        ON DELETE CASCADE,
    question_type VARCHAR(30) NOT NULL
        CHECK (question_type IN (
            'multiple_choice',
            'fill_blank',
            'essay'
        )),
    question_text TEXT NOT NULL,
    image_url TEXT,
    audio_url TEXT,
    points NUMERIC(7,2) NOT NULL DEFAULT 1
        CHECK (points >= 0),
    sort_order INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- 7. ANSWER OPTIONS: Các lựa chọn
CREATE TABLE IF NOT EXISTS answer_options (
    id BIGSERIAL PRIMARY KEY,
    question_id BIGINT NOT NULL REFERENCES questions(id)
        ON DELETE CASCADE,
    option_label VARCHAR(5) NOT NULL,
    option_text TEXT NOT NULL,
    is_correct BOOLEAN DEFAULT FALSE,
    UNIQUE(question_id, option_label)
);


-- 8. EXAM ATTEMPTS: Lượt làm bài
CREATE TABLE IF NOT EXISTS exam_attempts (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id),
    student_id BIGINT NOT NULL REFERENCES users(id),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'in_progress'
        CHECK (status IN (
            'in_progress',
            'submitted',
            'graded'
        )),
    listening_score NUMERIC(7,2) DEFAULT 0,
    reading_score NUMERIC(7,2) DEFAULT 0,
    writing_score NUMERIC(7,2) DEFAULT 0,
    total_score NUMERIC(7,2),
    UNIQUE(exam_id, student_id, started_at)
);


-- 9. STUDENT ANSWERS: Câu trả lời
CREATE TABLE IF NOT EXISTS student_answers (
    id BIGSERIAL PRIMARY KEY,
    attempt_id BIGINT NOT NULL REFERENCES exam_attempts(id)
        ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES questions(id),
    selected_option_id BIGINT REFERENCES answer_options(id),
    answer_text TEXT,
    is_correct BOOLEAN,
    awarded_points NUMERIC(7,2) DEFAULT 0,
    graded_at TIMESTAMPTZ,
    UNIQUE(attempt_id, question_id)
);


-- 10. WRITING SCORES: Điểm bài viết
CREATE TABLE IF NOT EXISTS writing_scores (
    id BIGSERIAL PRIMARY KEY,
    attempt_id BIGINT NOT NULL REFERENCES exam_attempts(id)
        ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES questions(id),
    teacher_id BIGINT REFERENCES users(id),
    score NUMERIC(7,2) NOT NULL DEFAULT 0,
    feedback TEXT,
    graded_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(attempt_id, question_id)
);


-- 11. INDEXES: Tăng tốc truy vấn
CREATE INDEX IF NOT EXISTS idx_users_email
ON users(email);

CREATE INDEX IF NOT EXISTS idx_exams_level
ON exams(level_id);

CREATE INDEX IF NOT EXISTS idx_exams_teacher
ON exams(teacher_id);

CREATE INDEX IF NOT EXISTS idx_questions_section
ON questions(section_id);

CREATE INDEX IF NOT EXISTS idx_attempts_student
ON exam_attempts(student_id);

CREATE INDEX IF NOT EXISTS idx_answers_attempt
ON student_answers(attempt_id);


-- ==================================================
-- END DATABASE
-- ==================================================
