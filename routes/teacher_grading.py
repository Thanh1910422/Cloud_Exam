from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    render_template,
    current_app,
    flash,
    redirect,
    url_for,
    session,
    abort,
    request
)
from psycopg2.extras import RealDictCursor
from werkzeug.exceptions import HTTPException

from config.database import get_connection
from routes.decorators import role_required


teacher_grading_bp = Blueprint(
    "teacher_grading",
    __name__,
    url_prefix="/teacher/grading"
)


def get_teacher_attempt(cursor, attempt_id):
    """Lượt thi thuộc đề thi do giáo viên đang đăng nhập phụ trách."""
    cursor.execute("""
        SELECT
            exam_attempts.*,
            exams.title AS exam_title,
            users.full_name AS student_name,
            users.email AS student_email
        FROM exam_attempts
        JOIN exams ON exam_attempts.exam_id = exams.id
        JOIN users ON exam_attempts.student_id = users.id
        WHERE exam_attempts.id = %s
          AND exams.teacher_id = %s
    """, (attempt_id, session.get("user_id")))
    return cursor.fetchone()


# ==========================================
# DANH SÁCH BÀI CẦN CHẤM
# ==========================================
@teacher_grading_bp.route("/")
@role_required("teacher")
def pending():
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT
                    exam_attempts.id,
                    exam_attempts.status,
                    exam_attempts.submitted_at,
                    exam_attempts.writing_score,
                    exam_attempts.total_score,
                    exams.title AS exam_title,
                    users.full_name AS student_name,
                    COUNT(student_answers.id) FILTER (
                        WHERE questions.question_type = 'essay'
                          AND student_answers.answer_text IS NOT NULL
                    ) AS essay_count
                FROM exam_attempts
                JOIN exams ON exam_attempts.exam_id = exams.id
                JOIN users ON exam_attempts.student_id = users.id
                LEFT JOIN student_answers ON student_answers.attempt_id = exam_attempts.id
                LEFT JOIN questions ON student_answers.question_id = questions.id
                WHERE exams.teacher_id = %s
                  AND exam_attempts.status IN ('submitted', 'graded')
                GROUP BY exam_attempts.id, exams.title, users.full_name
                HAVING COUNT(student_answers.id) FILTER (
                    WHERE questions.question_type = 'essay'
                      AND student_answers.answer_text IS NOT NULL
                ) > 0
                ORDER BY (exam_attempts.status = 'submitted') DESC,
                         exam_attempts.submitted_at DESC
                LIMIT 100
            """, (session.get("user_id"),))
            attempts = cursor.fetchall()

        return render_template("teacher/grading_list.html", attempts=attempts)

    except Exception:
        current_app.logger.exception("Cannot load grading list")
        flash("Không thể tải danh sách bài cần chấm.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()


# ==========================================
# CHẤM MỘT LƯỢT THI
# ==========================================
@teacher_grading_bp.route("/<int:attempt_id>", methods=["GET", "POST"])
@role_required("teacher")
def grade(attempt_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            attempt = get_teacher_attempt(cursor, attempt_id)
            if not attempt:
                abort(404)

            cursor.execute("""
                SELECT
                    questions.id,
                    questions.sort_order,
                    questions.question_text,
                    questions.image_url,
                    questions.points,
                    student_answers.answer_text,
                    student_answers.awarded_points,
                    writing_scores.score,
                    writing_scores.feedback,
                    (SELECT option_text FROM answer_options
                      WHERE answer_options.question_id = questions.id
                        AND answer_options.is_correct
                      LIMIT 1) AS reference_answer
                FROM questions
                JOIN exam_sections ON questions.section_id = exam_sections.id
                LEFT JOIN student_answers
                    ON student_answers.question_id = questions.id
                   AND student_answers.attempt_id = %s
                LEFT JOIN writing_scores
                    ON writing_scores.question_id = questions.id
                   AND writing_scores.attempt_id = %s
                WHERE exam_sections.exam_id = %s
                  AND questions.question_type = 'essay'
                ORDER BY questions.sort_order
            """, (attempt_id, attempt_id, attempt["exam_id"]))
            essays = cursor.fetchall()

            if request.method == "POST":
                for essay in essays:
                    raw = request.form.get(f"score_{essay['id']}", "").strip()
                    feedback = request.form.get(f"feedback_{essay['id']}", "").strip()[:2000] or None

                    if raw == "":
                        continue
                    try:
                        score = Decimal(raw.replace(",", "."))
                    except InvalidOperation:
                        flash(f"Điểm câu {essay['sort_order']} không hợp lệ.", "error")
                        return redirect(url_for("teacher_grading.grade", attempt_id=attempt_id))

                    if score < 0 or score > Decimal(essay["points"]):
                        flash(
                            f"Điểm câu {essay['sort_order']} phải từ 0 đến {essay['points']}.",
                            "error"
                        )
                        return redirect(url_for("teacher_grading.grade", attempt_id=attempt_id))

                    cursor.execute("""
                        INSERT INTO writing_scores
                            (attempt_id, question_id, teacher_id, score, feedback, graded_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                            teacher_id = EXCLUDED.teacher_id,
                            score = EXCLUDED.score,
                            feedback = EXCLUDED.feedback,
                            graded_at = NOW()
                    """, (attempt_id, essay["id"], session.get("user_id"), score, feedback))

                    cursor.execute("""
                        INSERT INTO student_answers
                            (attempt_id, question_id, answer_text, is_correct, awarded_points, graded_at)
                        VALUES (%s, %s, NULL, %s, %s, NOW())
                        ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                            is_correct = EXCLUDED.is_correct,
                            awarded_points = EXCLUDED.awarded_points,
                            graded_at = NOW()
                    """, (attempt_id, essay["id"], score > 0, score))

                # Tính lại điểm Viết và tổng điểm từ toàn bộ câu trả lời
                cursor.execute("""
                    SELECT exam_sections.section_type,
                           COALESCE(SUM(student_answers.awarded_points), 0) AS total
                    FROM student_answers
                    JOIN questions ON student_answers.question_id = questions.id
                    JOIN exam_sections ON questions.section_id = exam_sections.id
                    WHERE student_answers.attempt_id = %s
                    GROUP BY exam_sections.section_type
                """, (attempt_id,))
                by_section = {r["section_type"]: r["total"] for r in cursor.fetchall()}

                # Còn câu tự luận có bài làm mà chưa chấm -> vẫn 'submitted'
                cursor.execute("""
                    SELECT COUNT(*) AS n
                    FROM student_answers
                    JOIN questions ON student_answers.question_id = questions.id
                    LEFT JOIN writing_scores
                        ON writing_scores.attempt_id = student_answers.attempt_id
                       AND writing_scores.question_id = student_answers.question_id
                    WHERE student_answers.attempt_id = %s
                      AND questions.question_type = 'essay'
                      AND student_answers.answer_text IS NOT NULL
                      AND writing_scores.id IS NULL
                """, (attempt_id,))
                remaining = cursor.fetchone()["n"]

                cursor.execute("""
                    UPDATE exam_attempts
                    SET listening_score = %s,
                        reading_score = %s,
                        writing_score = %s,
                        total_score = %s,
                        status = %s
                    WHERE id = %s
                """, (
                    by_section.get("listening", 0),
                    by_section.get("reading", 0),
                    by_section.get("writing", 0),
                    sum(by_section.values()),
                    "submitted" if remaining else "graded",
                    attempt_id,
                ))

                connection.commit()

                if remaining:
                    flash(f"Đã lưu. Còn {remaining} câu chưa chấm.", "success")
                    return redirect(url_for("teacher_grading.grade", attempt_id=attempt_id))

                flash(f"Đã chấm xong bài của {attempt['student_name']}.", "success")
                return redirect(url_for("teacher_grading.pending"))

        return render_template(
            "teacher/grading_detail.html",
            attempt=attempt,
            essays=essays
        )

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot grade attempt")
        flash("Không thể lưu điểm. Vui lòng thử lại.", "error")
        return redirect(url_for("teacher_grading.pending"))

    finally:
        if connection:
            connection.close()
