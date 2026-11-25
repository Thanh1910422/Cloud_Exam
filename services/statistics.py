"""
Truy vấn thống kê dùng chung cho trang admin và trang giáo viên.

- days      : chỉ tính dữ liệu trong N ngày gần nhất (None = toàn bộ)
- teacher_id: chỉ tính các đề thi do giáo viên này phụ trách (None = mọi đề)

Điểm tối đa của mỗi đề = tổng điểm các câu hỏi (200 với HSK1-2, 300 với HSK3-6),
nên kết quả các cấp được so sánh theo % điểm. Đạt = >= 60% điểm tối đa.
"""

PASS_RATIO = 0.6
PERIOD_CHOICES = {"7": 7, "30": 30, "90": 90, "all": None}


def _period(column, days):
    """Điều kiện thời gian cho câu SQL (days đã được kiểm tra là số nguyên)."""
    if days is None:
        return "TRUE", ()
    return f"{column} >= NOW() - (%s * INTERVAL '1 day')", (days,)


# Bảng tạm: các lượt thi đã nộp + điểm tối đa của đề + % điểm
ATTEMPTS_CTE = """
    WITH exam_max AS (
        SELECT exam_sections.exam_id, SUM(questions.points) AS max_score
        FROM questions
        JOIN exam_sections ON questions.section_id = exam_sections.id
        GROUP BY exam_sections.exam_id
    ),
    done AS (
        SELECT
            exam_attempts.*,
            exams.title AS exam_title,
            exams.teacher_id,
            exam_max.max_score,
            CASE WHEN exam_max.max_score > 0
                 THEN exam_attempts.total_score * 100.0 / exam_max.max_score END AS percent
        FROM exam_attempts
        JOIN exams ON exam_attempts.exam_id = exams.id
        LEFT JOIN exam_max ON exam_max.exam_id = exams.id
        WHERE exam_attempts.status IN ('submitted', 'graded')
          AND {period}
          AND {teacher}
    )
"""


def _attempts_cte(days, teacher_id):
    period_sql, period_args = _period("exam_attempts.submitted_at", days)
    if teacher_id is None:
        teacher_sql, teacher_args = "TRUE", ()
    else:
        teacher_sql, teacher_args = "exams.teacher_id = %s", (teacher_id,)
    return (
        ATTEMPTS_CTE.format(period=period_sql, teacher=teacher_sql),
        period_args + teacher_args,
    )


# ==========================================
# CHỈ SỐ TỔNG QUAN
# ==========================================
def result_summary(cursor, days=None, teacher_id=None):
    cte, args = _attempts_cte(days, teacher_id)
    cursor.execute(cte + f"""
        SELECT
            COUNT(*) AS attempts,
            COUNT(DISTINCT student_id) AS students,
            ROUND(AVG(percent)::numeric, 1) AS avg_percent,
            ROUND(100.0 * AVG(CASE WHEN percent >= {PASS_RATIO * 100} THEN 1 ELSE 0 END)::numeric, 1)
                AS pass_rate,
            COUNT(*) FILTER (WHERE status = 'submitted') AS pending_grading
        FROM done
    """, args)
    return cursor.fetchone()


def account_summary(cursor, days=None):
    period_sql, period_args = _period("users.created_at", days)
    cursor.execute(f"""
        SELECT
            roles.role_name,
            COUNT(users.id) AS total,
            COUNT(users.id) FILTER (WHERE users.is_active) AS active,
            COUNT(users.id) FILTER (WHERE {period_sql}) AS new_in_period
        FROM roles
        LEFT JOIN users ON users.role_id = roles.id
        GROUP BY roles.role_name
    """, period_args)
    rows = {r["role_name"]: r for r in cursor.fetchall()}
    empty = {"total": 0, "active": 0, "new_in_period": 0}
    return {role: rows.get(role, empty) for role in ("student", "teacher", "admin")}


def exam_summary(cursor, teacher_id=None):
    teacher_sql = "TRUE" if teacher_id is None else "teacher_id = %s"
    cursor.execute(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'published') AS published,
            COUNT(*) FILTER (WHERE status = 'draft') AS draft
        FROM exams
        WHERE {teacher_sql}
    """, () if teacher_id is None else (teacher_id,))
    return cursor.fetchone()


# ==========================================
# TÀI KHOẢN ĐĂNG KÝ
# ==========================================
def registrations_by_day(cursor, days=30):
    """Số học viên đăng ký mỗi ngày (tối đa 90 ngày gần nhất, theo giờ Việt Nam)."""
    days = min(days or 30, 90)
    cursor.execute("""
        WITH day_list AS (
            SELECT generate_series(
                (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - (%s - 1),
                (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date,
                INTERVAL '1 day'
            )::date AS day
        )
        SELECT
            day_list.day,
            COUNT(users.id) AS registrations
        FROM day_list
        LEFT JOIN users
            ON (users.created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = day_list.day
           AND users.role_id = (SELECT id FROM roles WHERE role_name = 'student')
        GROUP BY day_list.day
        ORDER BY day_list.day
    """, (days,))
    return cursor.fetchall()


def recent_accounts(cursor, limit=20):
    cursor.execute("""
        SELECT
            users.full_name,
            users.email,
            roles.role_name,
            users.is_active,
            users.created_at,
            COUNT(exam_attempts.id) FILTER (
                WHERE exam_attempts.status IN ('submitted', 'graded')
            ) AS attempts
        FROM users
        JOIN roles ON users.role_id = roles.id
        LEFT JOIN exam_attempts ON exam_attempts.student_id = users.id
        GROUP BY users.id, roles.role_name
        ORDER BY users.created_at DESC
        LIMIT %s
    """, (limit,))
    return cursor.fetchall()


# ==========================================
# GIẢNG VIÊN
# ==========================================
def teacher_stats(cursor, days=None):
    cte, args = _attempts_cte(days, None)
    cursor.execute(cte + f"""
        SELECT
            users.id,
            users.full_name,
            users.email,
            users.is_active,
            users.created_at,
            (SELECT COUNT(*) FROM exams WHERE exams.teacher_id = users.id) AS exams_total,
            (SELECT COUNT(*) FROM exams
              WHERE exams.teacher_id = users.id AND exams.status = 'published') AS exams_published,
            (SELECT COUNT(*) FROM questions
              JOIN exam_sections ON questions.section_id = exam_sections.id
              JOIN exams ON exam_sections.exam_id = exams.id
              WHERE exams.teacher_id = users.id) AS questions,
            COUNT(done.id) AS attempts,
            COUNT(DISTINCT done.student_id) AS students,
            ROUND(AVG(done.percent)::numeric, 1) AS avg_percent,
            ROUND(100.0 * AVG(CASE WHEN done.id IS NULL THEN NULL
                                   WHEN done.percent >= {PASS_RATIO * 100} THEN 1 ELSE 0 END)::numeric, 1)
                AS pass_rate,
            COUNT(done.id) FILTER (WHERE done.status = 'submitted') AS pending_grading
        FROM users
        JOIN roles ON users.role_id = roles.id AND roles.role_name = 'teacher'
        LEFT JOIN done ON done.teacher_id = users.id
        GROUP BY users.id
        ORDER BY attempts DESC, users.full_name
    """, args)
    return cursor.fetchall()


# ==========================================
# KẾT QUẢ THI
# ==========================================
def exam_stats(cursor, days=None, teacher_id=None):
    cte, args = _attempts_cte(days, teacher_id)
    teacher_sql = "TRUE" if teacher_id is None else "exams.teacher_id = %s"
    cursor.execute(cte + f"""
        SELECT
            exams.id,
            exams.title,
            exams.status,
            hsk_levels.level_name,
            hsk_levels.level_number,
            teacher.full_name AS teacher_name,
            exam_max.max_score,
            COUNT(done.id) AS attempts,
            COUNT(DISTINCT done.student_id) AS students,
            ROUND(AVG(done.total_score)::numeric, 1) AS avg_total,
            ROUND(AVG(done.listening_score)::numeric, 1) AS avg_listening,
            ROUND(AVG(done.reading_score)::numeric, 1) AS avg_reading,
            ROUND(AVG(done.writing_score)::numeric, 1) AS avg_writing,
            MAX(done.total_score) AS best,
            ROUND(100.0 * AVG(CASE WHEN done.id IS NULL THEN NULL
                                   WHEN done.percent >= {PASS_RATIO * 100} THEN 1 ELSE 0 END)::numeric, 1)
                AS pass_rate,
            EXISTS (SELECT 1 FROM exam_sections ws
                     JOIN questions wq ON wq.section_id = ws.id
                     WHERE ws.exam_id = exams.id AND ws.section_type = 'writing') AS has_writing
        FROM exams
        JOIN hsk_levels ON exams.level_id = hsk_levels.id
        LEFT JOIN users AS teacher ON exams.teacher_id = teacher.id
        LEFT JOIN exam_max ON exam_max.exam_id = exams.id
        LEFT JOIN done ON done.exam_id = exams.id
        WHERE {teacher_sql}
        GROUP BY exams.id, hsk_levels.level_name, hsk_levels.level_number,
                 teacher.full_name, exam_max.max_score
        ORDER BY attempts DESC, hsk_levels.level_number, exams.title
    """, args + (() if teacher_id is None else (teacher_id,)))
    return cursor.fetchall()


def score_distribution(cursor, days=None, teacher_id=None):
    """Số lượt thi theo khoảng % điểm: 0-9, 10-19, ..., 90-100."""
    cte, args = _attempts_cte(days, teacher_id)
    cursor.execute(cte + """
        SELECT LEAST(FLOOR(percent / 10), 9)::int AS bucket, COUNT(*) AS attempts
        FROM done
        WHERE percent IS NOT NULL
        GROUP BY bucket
    """, args)
    counts = {r["bucket"]: r["attempts"] for r in cursor.fetchall()}
    return [
        {
            "label": f"{b * 10}–{b * 10 + 9 if b < 9 else 100}%",
            "attempts": counts.get(b, 0),
            "passing": b * 10 >= PASS_RATIO * 100,
        }
        for b in range(10)
    ]


def hardest_questions(cursor, days=None, teacher_id=None, limit=10, min_answers=3):
    """Các câu có tỉ lệ làm đúng thấp nhất (chỉ câu máy chấm, có đủ số lượt trả lời)."""
    cte, args = _attempts_cte(days, teacher_id)
    cursor.execute(cte + """
        SELECT
            done.exam_title,
            questions.sort_order,
            exam_sections.section_type,
            LEFT(REPLACE(questions.question_text, E'\\n', ' '), 60) AS question_text,
            COUNT(*) AS answers,
            ROUND(100.0 * AVG(CASE WHEN student_answers.is_correct THEN 1 ELSE 0 END)::numeric, 1)
                AS correct_rate
        FROM student_answers
        JOIN done ON student_answers.attempt_id = done.id
        JOIN questions ON student_answers.question_id = questions.id
        JOIN exam_sections ON questions.section_id = exam_sections.id
        WHERE questions.question_type IN ('multiple_choice', 'fill_blank')
          AND EXISTS (                     -- bỏ câu chưa nhập đáp án đúng
              SELECT 1 FROM answer_options
              WHERE answer_options.question_id = questions.id
                AND answer_options.is_correct
                AND (questions.question_type = 'multiple_choice'
                     OR COALESCE(answer_options.option_text, '') <> '')
          )
        GROUP BY done.exam_title, questions.id, exam_sections.section_type
        HAVING COUNT(*) >= %s
        ORDER BY correct_rate ASC, answers DESC
        LIMIT %s
    """, args + (min_answers, limit))
    return cursor.fetchall()


def parse_period(value):
    """'7' | '30' | '90' | 'all' -> (key, days). Mặc định 30 ngày."""
    key = value if value in PERIOD_CHOICES else "30"
    return key, PERIOD_CHOICES[key]
