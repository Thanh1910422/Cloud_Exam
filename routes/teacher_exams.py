
from flask import (
    Blueprint,
    render_template,
    current_app,
    flash,
    redirect,
    url_for,
    session,
    request,
    abort
)

from psycopg2.extras import RealDictCursor
from config.database import get_connection
from config.storage import storage
from routes.decorators import role_required
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from uuid import uuid4


teacher_exam_bp = Blueprint(
    "teacher_exam",
    __name__,
    url_prefix="/teacher/exams"
)


# Các định dạng file được cho phép
ALLOWED_EXTENSIONS = {
    "exam_document": {"pdf", "docx"},
    "listening_audio": {"mp3", "wav"},
    "answer_key": {"pdf", "docx"},
    "question_image": {"jpg", "jpeg", "png"}
}


# ==========================================
# DANH SÁCH ĐỀ THI ĐƯỢC PHÂN CÔNG
# ==========================================
@teacher_exam_bp.route("/")
@role_required("teacher")
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
                    exams.created_at
                FROM exams
                JOIN hsk_levels
                    ON exams.level_id = hsk_levels.id
                WHERE exams.teacher_id = %s
                ORDER BY exams.created_at DESC
            """, (session.get("user_id"),))

            exams = cursor.fetchall()

        return render_template(
            "teacher/exams.html",
            exams=exams
        )

    except Exception:
        current_app.logger.exception("Cannot load teacher exams")
        flash("Không thể tải danh sách đề thi.", "error")
        return redirect(url_for("teacher.dashboard"))

    finally:
        if connection:
            connection.close()


# ==========================================
# TẢI TÀI LIỆU ĐỀ THI LÊN SUPABASE STORAGE
# ==========================================
@teacher_exam_bp.route("/<int:exam_id>/upload", methods=["POST"])
@role_required("teacher")
def upload_exam_file(exam_id):
    connection = None
    uploaded_path = None

    try:
        file = request.files.get("file")
        file_type = request.form.get("file_type", "").strip()

        if not file or not file.filename:
            flash("Bạn chưa chọn file.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        if file_type not in ALLOWED_EXTENSIONS:
            flash("Loại tài liệu không hợp lệ.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        original_filename = secure_filename(file.filename)

        if not original_filename or "." not in original_filename:
            flash("Tên file không hợp lệ.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        extension = original_filename.rsplit(".", 1)[1].lower()

        if extension not in ALLOWED_EXTENSIONS[file_type]:
            flash("Định dạng file không được hỗ trợ.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        file_data = file.read()

        if not file_data:
            flash("File tải lên đang trống.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        if len(file_data) > 50 * 1024 * 1024:
            flash("File không được vượt quá 50 MB.", "error")
            return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))

        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id
                FROM exams
                WHERE id = %s AND teacher_id = %s
            """, (exam_id, session.get("user_id")))

            exam = cursor.fetchone()

            if not exam:
                abort(404)

            uploaded_path = (
                f"exams/{exam_id}/{file_type}/"
                f"{uuid4().hex}_{original_filename}"
            )

            storage.upload(
                uploaded_path,
                file_data,
                {
                    "content-type": file.mimetype or "application/octet-stream",
                    "upsert": "false"
                }
            )

            cursor.execute("""
                INSERT INTO exam_files (
                    exam_id,
                    uploaded_by,
                    file_type,
                    original_filename,
                    storage_path,
                    mime_type,
                    size_bytes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                exam_id,
                session.get("user_id"),
                file_type,
                original_filename,
                uploaded_path,
                file.mimetype,
                len(file_data)
            ))

        connection.commit()

        flash("Tải tài liệu lên thành công!", "success")

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()

        if uploaded_path:
            try:
                storage.remove([uploaded_path])
            except Exception:
                current_app.logger.exception("Cannot remove uploaded file")

        current_app.logger.exception("Cannot upload exam file")
        flash("Không thể tải tài liệu lên. Vui lòng kiểm tra lại.", "error")

    finally:
        if connection:
            connection.close()

    return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))
