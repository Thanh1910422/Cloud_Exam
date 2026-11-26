from flask import Blueprint, render_template, current_app, flash, redirect, url_for, session, abort
from psycopg2.extras import RealDictCursor

from config.database import get_connection


levels_bp = Blueprint("levels", __name__)

EXAM_COLUMNS = """
    exams.id,
    exams.title,
    exams.description,
    exams.status,
    exams.duration_minutes,
    exams.created_at,
    teacher.full_name AS teacher_name,
    (SELECT COUNT(*) FROM questions
       JOIN exam_sections ON questions.section_id = exam_sections.id
      WHERE exam_sections.exam_id = exams.id) AS question_count,
    (SELECT COUNT(*) FROM exam_attempts
      WHERE exam_attempts.exam_id = exams.id
        AND exam_attempts.status IN ('submitted', 'graded')) AS attempt_count
"""


def published_counts(cursor):
    """{cấp: số đề đã xuất bản và có câu hỏi} - dùng cho trang chủ."""
    cursor.execute("""
        SELECT hsk_levels.level_number, COUNT(exams.id) AS n
        FROM hsk_levels
        LEFT JOIN exams ON exams.level_id = hsk_levels.id
         AND exams.status = 'published'
         AND EXISTS (SELECT 1 FROM questions
                       JOIN exam_sections ON questions.section_id = exam_sections.id
                      WHERE exam_sections.exam_id = exams.id)
        GROUP BY hsk_levels.level_number
    """)
    return {r["level_number"]: r["n"] for r in cursor.fetchall()}


@levels_bp.route("/hsk/<int:level_number>")
def level_exams(level_number):
    if not 1 <= level_number <= 6:
        abort(404)

    role = session.get("role")
    user_id = session.get("user_id")
    connection = None

    try:
        connection = get_connection()
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT id, level_name FROM hsk_levels WHERE level_number = %s",
                (level_number,))
            level = cursor.fetchone()
            if not level:
                abort(404)

            base = f"""
                SELECT {EXAM_COLUMNS}
                FROM exams
                LEFT JOIN users AS teacher ON exams.teacher_id = teacher.id
                WHERE exams.level_id = %s
            """
            if role == "admin":
                cursor.execute(base + " ORDER BY exams.created_at DESC", (level["id"],))
            elif role == "teacher":
                cursor.execute(base + " AND exams.teacher_id = %s ORDER BY exams.created_at DESC",
                               (level["id"], user_id))
            else:
                cursor.execute(base + """
                    AND exams.status = 'published'
                    AND EXISTS (SELECT 1 FROM questions
                                  JOIN exam_sections ON questions.section_id = exam_sections.id
                                 WHERE exam_sections.exam_id = exams.id)
                    ORDER BY exams.title
                """, (level["id"],))
            exams = cursor.fetchall()

            # Học viên: lần thi gần nhất của từng đề (để hiện "Làm tiếp" / điểm cao nhất)
            my_attempts = {}
            if role == "student" and exams:
                cursor.execute("""
                    SELECT exam_id,
                           BOOL_OR(status = 'in_progress') AS in_progress,
                           MAX(total_score) FILTER (WHERE status IN ('submitted', 'graded')) AS best,
                           COUNT(*) FILTER (WHERE status IN ('submitted', 'graded')) AS times
                    FROM exam_attempts
                    WHERE student_id = %s
                    GROUP BY exam_id
                """, (user_id,))
                my_attempts = {r["exam_id"]: r for r in cursor.fetchall()}

        from routes.teacher_builder import supported_levels

        return render_template(
            "level_exams.html",
            level=level,
            level_number=level_number,
            exams=exams,
            role=role,
            my_attempts=my_attempts,
            auto_supported=level_number in supported_levels(),
        )

    except Exception as error:
        if getattr(error, "code", None) == 404:
            raise
        current_app.logger.exception("Cannot load level exams")
        flash("Không thể tải danh sách đề thi.", "error")
        return redirect(url_for("index"))

    finally:
        if connection:
            connection.close()
