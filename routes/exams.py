
from flask import (
    Blueprint,
    render_template,
    current_app,
    flash,
    redirect,
    url_for,
    request
)
from psycopg2.extras import RealDictCursor

from config.database import get_connection
from routes.decorators import role_required


exam_bp = Blueprint(
    "exam",
    __name__,
    url_prefix="/admin/exams"
)


# ==========================================
# LẤY DANH SÁCH CẤP ĐỘ VÀ GIẢNG VIÊN
# ==========================================
def get_exam_form_data(cursor):
    cursor.execute("""
        SELECT id, level_name
        FROM hsk_levels
        ORDER BY level_number
    """)
    levels = cursor.fetchall()

    cursor.execute("""
        SELECT id, full_name, email
        FROM users
        WHERE role_id = (
            SELECT id FROM roles
            WHERE role_name = 'teacher'
        )
        AND is_active = TRUE
        ORDER BY full_name
    """)
    teachers = cursor.fetchall()

    return levels, teachers


# ==========================================
# DANH SÁCH ĐỀ THI
# ==========================================
@exam_bp.route("/")
@role_required("admin")
def exams():
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT
                    exams.id,
                    exams.title,
                    exams.description,
                    hsk_levels.level_name,
                    exams.duration_minutes,
                    exams.status,
                    exams.created_at,
                    users.full_name AS teacher_name
                FROM exams
                JOIN hsk_levels
                    ON exams.level_id = hsk_levels.id
                LEFT JOIN users
                    ON exams.teacher_id = users.id
                ORDER BY exams.created_at DESC
            """)

            exam_list = cursor.fetchall()

        return render_template(
            "admin/exams.html",
            exams=exam_list
        )

    except Exception:
        current_app.logger.exception("Cannot load exams")
        flash("Không thể tải danh sách đề thi.", "error")
        return redirect(url_for("admin.dashboard"))

    finally:
        if connection:
            connection.close()


# ==========================================
# TẠO ĐỀ THI MỚI
# ==========================================
@exam_bp.route("/new", methods=["GET", "POST"])
@role_required("admin")
def create_exam():
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            levels, teachers = get_exam_form_data(cursor)

            if request.method == "POST":
                title = request.form.get("title", "").strip()
                description = request.form.get("description", "").strip()
                level_id = request.form.get("level_id")
                teacher_id = request.form.get("teacher_id") or None
                duration = request.form.get("duration_minutes")
                status = request.form.get("status", "draft")

                try:
                    level_id = int(level_id)
                    duration = int(duration)

                    if teacher_id:
                        teacher_id = int(teacher_id)

                    if not title or duration <= 0:
                        raise ValueError

                    if status not in ("draft", "published"):
                        raise ValueError

                    cursor.execute(
                        "SELECT id FROM hsk_levels WHERE id = %s",
                        (level_id,)
                    )
                    if not cursor.fetchone():
                        raise ValueError

                    if teacher_id:
                        cursor.execute("""
                            SELECT users.id
                            FROM users
                            JOIN roles ON users.role_id = roles.id
                            WHERE users.id = %s
                              AND roles.role_name = 'teacher'
                              AND users.is_active = TRUE
                        """, (teacher_id,))

                        if not cursor.fetchone():
                            raise ValueError

                except (ValueError, TypeError):
                    flash("Thông tin đề thi không hợp lệ.", "error")
                    return render_template(
                        "admin/create_exam.html",
                        levels=levels,
                        teachers=teachers
                    )

                cursor.execute("""
                    INSERT INTO exams (
                        title,
                        description,
                        level_id,
                        teacher_id,
                        duration_minutes,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    title,
                    description,
                    level_id,
                    teacher_id,
                    duration,
                    status
                ))

                connection.commit()

                flash("Tạo đề thi thành công!", "success")
                return redirect(url_for("exam.exams"))

        return render_template(
            "admin/create_exam.html",
            levels=levels,
            teachers=teachers
        )

    except Exception:
        if connection:
            connection.rollback()

        current_app.logger.exception("Cannot create exam")
        flash("Không thể tạo đề thi. Vui lòng kiểm tra lại dữ liệu.", "error")
        return redirect(url_for("exam.exams"))

    finally:
        if connection:
            connection.close()


# ==========================================
# CHỈNH SỬA ĐỀ THI
# ==========================================
@exam_bp.route("/<int:exam_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_exam(exam_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            levels, teachers = get_exam_form_data(cursor)

            cursor.execute("""
                SELECT *
                FROM exams
                WHERE id = %s
            """, (exam_id,))

            exam = cursor.fetchone()

            if not exam:
                flash("Không tìm thấy đề thi.", "error")
                return redirect(url_for("exam.exams"))

            if request.method == "POST":
                title = request.form.get("title", "").strip()
                description = request.form.get("description", "").strip()
                level_id = request.form.get("level_id")
                teacher_id = request.form.get("teacher_id") or None
                duration = request.form.get("duration_minutes")
                status = request.form.get("status")

                try:
                    level_id = int(level_id)
                    duration = int(duration)

                    if teacher_id:
                        teacher_id = int(teacher_id)

                    if not title or duration <= 0:
                        raise ValueError

                    if status not in ("draft", "published", "archived"):
                        raise ValueError

                    cursor.execute(
                        "SELECT id FROM hsk_levels WHERE id = %s",
                        (level_id,)
                    )
                    if not cursor.fetchone():
                        raise ValueError

                    if teacher_id:
                        cursor.execute("""
                            SELECT users.id
                            FROM users
                            JOIN roles ON users.role_id = roles.id
                            WHERE users.id = %s
                              AND roles.role_name = 'teacher'
                              AND users.is_active = TRUE
                        """, (teacher_id,))

                        if not cursor.fetchone():
                            raise ValueError

                except (ValueError, TypeError):
                    flash("Thông tin chỉnh sửa không hợp lệ.", "error")
                    return render_template(
                        "admin/edit_exam.html",
                        exam=exam,
                        levels=levels,
                        teachers=teachers
                    )

                cursor.execute("""
                    UPDATE exams
                    SET
                        title = %s,
                        description = %s,
                        level_id = %s,
                        teacher_id = %s,
                        duration_minutes = %s,
                        status = %s
                    WHERE id = %s
                """, (
                    title,
                    description,
                    level_id,
                    teacher_id,
                    duration,
                    status,
                    exam_id
                ))

                connection.commit()

                flash("Cập nhật đề thi thành công!", "success")
                return redirect(url_for("exam.exams"))

        return render_template(
            "admin/edit_exam.html",
            exam=exam,
            levels=levels,
            teachers=teachers
        )

    except Exception:
        if connection:
            connection.rollback()

        current_app.logger.exception("Cannot edit exam")
        flash("Không thể chỉnh sửa đề thi.", "error")
        return redirect(url_for("exam.exams"))

    finally:
        if connection:
            connection.close()


# ==========================================
# XÓA ĐỀ THI
# ==========================================
@exam_bp.route("/<int:exam_id>/delete", methods=["POST"])
@role_required("admin")
def delete_exam(exam_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                DELETE FROM exams
                WHERE id = %s
                RETURNING id
            """, (exam_id,))

            deleted_exam = cursor.fetchone()

            if not deleted_exam:
                flash("Không tìm thấy đề thi cần xóa.", "error")
                return redirect(url_for("exam.exams"))

            connection.commit()

        flash("Xóa đề thi thành công!", "success")

    except Exception:
        if connection:
            connection.rollback()

        current_app.logger.exception("Cannot delete exam")
        flash(
            "Không thể xóa đề thi. Có thể đề thi đã có dữ liệu bài làm của học viên.",
            "error"
        )

    finally:
        if connection:
            connection.close()

    return redirect(url_for("exam.exams"))
