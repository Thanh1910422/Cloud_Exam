
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
from config.database import get_connection
from routes.decorators import role_required
from werkzeug.exceptions import HTTPException
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
            cursor.execute("""
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
            """, (exam_id, session.get("user_id")))

            exam = cursor.fetchone()

            if not exam:
                abort(404)

            cursor.execute("""
                SELECT
                    id,
                    section_type,
                    section_title,
                    time_limit_minutes,
                    sort_order
                FROM exam_sections
                WHERE exam_id = %s
                ORDER BY sort_order
            """, (exam_id,))

            sections = cursor.fetchall()

        return render_template(
            "teacher/exam_detail.html",
            exam=exam,
            sections=sections
        )

    except HTTPException:
        raise

    except Exception:
        current_app.logger.exception(
            "Cannot load teacher exam content"
        )
        flash("Không thể tải nội dung đề thi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()

@teacher_questions_bp.route(
    "/exams/<int:exam_id>/sections/add",
    methods=["POST"]
)
@role_required("teacher")
def add_section(exam_id):
    connection = None

    try:
        section_type = request.form.get("section_type", "").strip()
        section_title = request.form.get("section_title", "").strip()
        time_limit = request.form.get("time_limit_minutes", "").strip()

        allowed_types = ("listening", "reading", "writing")

        if section_type not in allowed_types:
            flash("Loại phần thi không hợp lệ.", "error")
            return redirect(url_for(
                "teacher_questions.exam_content",
                exam_id=exam_id
            ))

        if not section_title:
            flash("Vui lòng nhập tên phần thi.", "error")
            return redirect(url_for(
                "teacher_questions.exam_content",
                exam_id=exam_id
            ))

        try:
            time_limit = int(time_limit)
            if time_limit <= 0:
                raise ValueError
        except ValueError:
            flash("Thời gian phải là số nguyên lớn hơn 0.", "error")
            return redirect(url_for(
                "teacher_questions.exam_content",
                exam_id=exam_id
            ))

        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Kiểm tra đề thi có thuộc giáo viên đang đăng nhập không
            cursor.execute("""
                SELECT id
                FROM exams
                WHERE id = %s AND teacher_id = %s
            """, (exam_id, session.get("user_id")))

            exam = cursor.fetchone()

            if not exam:
                abort(404)

            # Xác định thứ tự phần thi tiếp theo
            cursor.execute("""
                SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                FROM exam_sections
                WHERE exam_id = %s
            """, (exam_id,))

            next_order = cursor.fetchone()["next_order"]

            # Thêm phần thi
            cursor.execute("""
                INSERT INTO exam_sections (
                    exam_id,
                    section_type,
                    section_title,
                    time_limit_minutes,
                    sort_order
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                exam_id,
                section_type,
                section_title,
                time_limit,
                next_order
            ))

        connection.commit()

        flash("Thêm phần thi thành công.", "success")

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception as error:
        if connection:
            connection.rollback()

        # PostgreSQL báo lỗi nếu phần thi cùng loại đã tồn tại
        if getattr(error, "pgcode", None) == "23505":
            flash("Phần thi này đã tồn tại trong đề thi.", "error")
        else:
            current_app.logger.exception("Cannot add exam section")
            flash("Không thể thêm phần thi.", "error")

    finally:
        if connection:
            connection.close()

    return redirect(url_for(
        "teacher_questions.exam_content",
        exam_id=exam_id
    ))

@teacher_questions_bp.route("/sections/<int:section_id>/questions")
@role_required("teacher")
def section_questions(section_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Kiểm tra phần thi có thuộc đề thi của giáo viên không
            cursor.execute("""
                SELECT
                    exam_sections.id,
                    exam_sections.section_title,
                    exam_sections.section_type,
                    exams.id AS exam_id,
                    exams.title AS exam_title
                FROM exam_sections
                JOIN exams
                    ON exam_sections.exam_id = exams.id
                WHERE exam_sections.id = %s
                  AND exams.teacher_id = %s
            """, (section_id, session.get("user_id")))

            section = cursor.fetchone()

            if not section:
                abort(404)

            # Lấy danh sách câu hỏi
            cursor.execute("""
                SELECT
                    id,
                    question_type,
                    question_text,
                    image_url,
                    audio_url,
                    points,
                    sort_order
                FROM questions
                WHERE section_id = %s
                ORDER BY sort_order, id
            """, (section_id,))

            questions = cursor.fetchall()

            # Lấy đáp án của từng câu hỏi
            for question in questions:
                cursor.execute("""
                    SELECT
                        id,
                        option_label,
                        option_text,
                        is_correct
                    FROM answer_options
                    WHERE question_id = %s
                    ORDER BY option_label
                """, (question["id"],))

                question["options"] = cursor.fetchall()

        return render_template(
            "teacher/questions.html",
            section=section,
            questions=questions
        )

    except HTTPException:
        raise

    except Exception:
        current_app.logger.exception(
            "Cannot load section questions"
        )
        flash("Không thể tải danh sách câu hỏi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()
