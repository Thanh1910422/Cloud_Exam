
from flask import (
    Blueprint,
    render_template,
    current_app,
    session,
    abort,
    flash,
    redirect,
    url_for
)

from psycopg2.extras import RealDictCursor
from config.database import get_connection
from routes.decorators import role_required


teacher_questions_bp = Blueprint(
    "teacher_questions",
    __name__,
    url_prefix="/teacher"
)


@teacher_questions_bp.route("/exams/<int:exam_id>/content")
@role_required("teacher")
def exam_content(exam_id):

    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:

            # Kiểm tra đề thi có thuộc giảng viên đang đăng nhập không
            cursor.execute(
                """
                SELECT
                    exams.id,
                    exams.title,
                    exams.description,
                    exams.duration_minutes,
                    exams.status,
                    hsk_levels.level_name
                FROM exams
                JOIN hsk_levels
                    ON exams.level_id = hsk_levels.id
                WHERE exams.id = %s
                  AND exams.teacher_id = %s
                """,
                (exam_id, session.get("user_id"))
            )

            exam = cursor.fetchone()

            # Không cho giảng viên xem đề thi của người khác
            if not exam:
                abort(404)

            # Lấy các phần thi của đề thi
            cursor.execute(
                """
                SELECT
                    id,
                    section_type,
                    section_title,
                    time_limit_minutes,
                    sort_order
                FROM exam_sections
                WHERE exam_id = %s
                ORDER BY sort_order, id
                """,
                (exam_id,)
            )

            sections = cursor.fetchall()

        return render_template(
            "teacher/exam_detail.html",
            exam=exam,
            sections=sections
        )

    except Exception:
        current_app.logger.exception(
            "Cannot load teacher exam content"
        )
        flash("Không thể tải nội dung đề thi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()
