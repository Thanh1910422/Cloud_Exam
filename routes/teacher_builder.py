import re
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    render_template,
    current_app,
    flash,
    redirect,
    url_for,
    session,
    abort,
    request,
    jsonify
)
from psycopg2.extras import RealDictCursor
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from config.database import get_connection
from routes.decorators import role_required
from services.exam_builder import BuildError, LEVELS_DIR


teacher_builder_bp = Blueprint("teacher_builder", __name__, url_prefix="/teacher/exams")

# Loại file -> (đuôi file cho phép, dung lượng tối đa MB). Supabase gói Free: tối đa 50 MB/file.
UPLOAD_RULES = {
    "exam_document": ({"pdf", "docx"}, 50),
    "listening_audio": ({"mp3", "wav", "m4a"}, 50),
    "answer_key": ({"pdf", "docx", "txt"}, 20),
}


def supported_levels():
    """Các cấp đã có file cấu hình định dạng đề (data/levels/hsk<N>.json)."""
    return sorted(
        int(m.group(1)) for p in Path(LEVELS_DIR).glob("hsk*.json")
        if (m := re.match(r"hsk(\d+)\.json$", p.name))
    )


def owned_exam(cursor, exam_id):
    cursor.execute("""
        SELECT exams.*, hsk_levels.level_number, hsk_levels.level_name
        FROM exams JOIN hsk_levels ON exams.level_id = hsk_levels.id
        WHERE exams.id = %s AND exams.teacher_id = %s
    """, (exam_id, session.get("user_id")))
    return cursor.fetchone()


def back_to(exam_id):
    return redirect(url_for("teacher_questions.exam_content", exam_id=exam_id))


def get_storage():
    from config.storage import storage
    return storage


# ==========================================
# TẠO ĐỀ THI MỚI
# ==========================================
@teacher_builder_bp.route("/new", methods=["GET", "POST"])
@role_required("teacher")
def new_exam():
    connection = None
    try:
        connection = get_connection()
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, level_name, level_number FROM hsk_levels ORDER BY level_number")
            levels = cursor.fetchall()

            if request.method == "POST":
                title = request.form.get("title", "").strip()[:200]
                description = request.form.get("description", "").strip()[:2000]
                try:
                    level_id = int(request.form.get("level_id", ""))
                    duration = int(request.form.get("duration_minutes", ""))
                    if not title or not (5 <= duration <= 300):
                        raise ValueError
                    if level_id not in {lv["id"] for lv in levels}:
                        raise ValueError
                except ValueError:
                    flash("Vui lòng nhập tên đề, chọn cấp độ và thời gian 5–300 phút.", "error")
                    return render_template("teacher/new_exam.html", levels=levels,
                                           supported=supported_levels(), form=request.form)

                cursor.execute("""
                    INSERT INTO exams (title, description, level_id, teacher_id, duration_minutes, status)
                    VALUES (%s, %s, %s, %s, %s, 'draft')
                    RETURNING id
                """, (title, description, level_id, session.get("user_id"), duration))
                exam_id = cursor.fetchone()["id"]
                connection.commit()

                flash("Đã tạo đề thi. Bước tiếp theo: tải file PDF đề lên.", "success")
                return back_to(exam_id)

        # Bấm "+ Tạo đề HSK4 mới" -> chọn sẵn HSK4
        preset = {}
        wanted = request.args.get("level", "")
        for lv in levels:
            if str(lv["level_number"]) == wanted:
                preset = {"level_id": str(lv["id"]),
                          "duration_minutes": str({1: 40, 2: 55, 3: 90, 4: 105, 5: 125, 6: 140}.get(lv["level_number"], 60))}
        return render_template("teacher/new_exam.html", levels=levels,
                               supported=supported_levels(), form=preset)

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot create exam (teacher)")
        flash("Không thể tạo đề thi.", "error")
        return redirect(url_for("teacher_exam.exams"))
    finally:
        if connection:
            connection.close()


# ==========================================
# TẢI FILE THẲNG LÊN SUPABASE
# ==========================================
@teacher_builder_bp.route("/<int:exam_id>/upload-url", methods=["POST"])
@role_required("teacher")
def upload_url(exam_id):
    data = request.get_json(silent=True) or {}
    file_type = data.get("file_type", "")
    filename = secure_filename(data.get("filename", ""))
    try:
        size = int(data.get("size", 0))
    except (TypeError, ValueError):
        size = 0

    if file_type not in UPLOAD_RULES:
        return jsonify(error="Loại tài liệu không hợp lệ."), 400
    extensions, max_mb = UPLOAD_RULES[file_type]
    if not filename or "." not in filename or filename.rsplit(".", 1)[1].lower() not in extensions:
        return jsonify(error=f"Chỉ nhận file: {', '.join(sorted(extensions))}."), 400
    if size <= 0 or size > max_mb * 1024 * 1024:
        return jsonify(error=f"File phải nhỏ hơn {max_mb} MB."), 400

    connection = None
    try:
        connection = get_connection()
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if not owned_exam(cursor, exam_id):
                return jsonify(error="Không tìm thấy đề thi."), 404

        path = f"exams/{exam_id}/{file_type}/{uuid4().hex}_{filename}"
        result = get_storage().create_signed_upload_url(path)
        url = result.get("signed_url") or result.get("signedUrl") or result.get("signedURL")
        if url and url.startswith("/"):
            import os
            url = os.getenv("SUPABASE_URL", "").rstrip("/") + "/storage/v1" + url
        if not url:
            raise RuntimeError(f"Không tạo được link tải lên: {result}")

        # Ghi nhớ đường dẫn đã cấp để bước 'upload-complete' chỉ nhận đúng file này
        pending = session.get("pending_uploads", {})
        pending[path] = {"exam_id": exam_id, "file_type": file_type, "filename": filename, "size": size}
        session["pending_uploads"] = dict(list(pending.items())[-10:])

        return jsonify(upload_url=url, path=path)

    except Exception:
        current_app.logger.exception("Cannot create signed upload url")
        return jsonify(error="Không tạo được link tải lên. Vui lòng thử lại."), 500
    finally:
        if connection:
            connection.close()


@teacher_builder_bp.route("/<int:exam_id>/upload-complete", methods=["POST"])
@role_required("teacher")
def upload_complete(exam_id):
    data = request.get_json(silent=True) or {}
    path = data.get("path", "")
    pending = session.get("pending_uploads", {})
    info = pending.get(path)

    if not info or info["exam_id"] != exam_id:
        return jsonify(error="Phiên tải lên không hợp lệ. Vui lòng tải lại."), 400

    connection = None
    try:
        connection = get_connection()
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if not owned_exam(cursor, exam_id):
                return jsonify(error="Không tìm thấy đề thi."), 404
            cursor.execute("""
                INSERT INTO exam_files
                    (exam_id, uploaded_by, file_type, original_filename, storage_path, mime_type, size_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (exam_id, session.get("user_id"), info["file_type"], info["filename"],
                  path, (data.get("mime_type") or "application/octet-stream")[:100], info["size"]))
        connection.commit()

        pending.pop(path, None)
        session["pending_uploads"] = pending
        flash(f"Đã tải lên: {info['filename']}", "success")
        return jsonify(ok=True)

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot register uploaded file")
        return jsonify(error="Không lưu được thông tin file."), 500
    finally:
        if connection:
            connection.close()


# ==========================================
# TẠO CÂU HỎI / CẬP NHẬT ĐÁP ÁN / XUẤT BẢN
# ==========================================
def _run(exam_id, action):
    """Chạy một thao tác trên đề của giáo viên, commit nếu thành công."""
    connection = None
    try:
        connection = get_connection()
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            exam = owned_exam(cursor, exam_id)
            if not exam:
                abort(404)
            message = action(cursor, exam)
        connection.commit()
        flash(message, "success")
    except HTTPException:
        if connection:
            connection.rollback()
        raise
    except BuildError as error:
        if connection:
            connection.rollback()
        flash(str(error), "error")
    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Exam builder action failed")
        flash("Có lỗi khi xử lý file đề. Kiểm tra lại file PDF hoặc báo quản trị viên.", "error")
    finally:
        if connection:
            connection.close()
    return back_to(exam_id)


@teacher_builder_bp.route("/<int:exam_id>/build", methods=["POST"])
@role_required("teacher")
def build(exam_id):
    from services.exam_pipeline import build_from_storage

    replace = request.form.get("replace") == "1"

    def action(cursor, exam):
        if exam["level_number"] not in supported_levels():
            raise BuildError(
                f"HSK{exam['level_number']} chưa có cấu hình định dạng đề nên chưa tạo tự động được."
            )
        r = build_from_storage(cursor, get_storage(), exam_id, replace=replace,
                               log=current_app.logger.info)
        text = f"Đã tạo {r['questions']} câu hỏi ({r['images']} ảnh)."
        text += (f" Đáp án: {r['with_answer']}/{r['questions']} câu, lấy từ {r['answer_source']}."
                 if r["answer_source"] else " Chưa có đáp án — tải file đáp án rồi bấm 'Cập nhật đáp án'.")
        if r["needs_review"]:
            text += f" Có {r['needs_review']} câu cần kiểm tra (dấu ⚠)."
        return text

    return _run(exam_id, action)


@teacher_builder_bp.route("/<int:exam_id>/update-answers", methods=["POST"])
@role_required("teacher")
def update_answers(exam_id):
    from services.exam_pipeline import update_answers_from_storage

    def action(cursor, exam):
        r = update_answers_from_storage(cursor, get_storage(), exam_id,
                                        log=current_app.logger.info)
        text = f"Đã cập nhật đáp án cho {r['updated']}/{r['total']} câu (từ {r['source']})."
        if r["skipped"]:
            text += " Bỏ qua: " + ", ".join(r["skipped"][:10])
        return text

    return _run(exam_id, action)


@teacher_builder_bp.route("/<int:exam_id>/status", methods=["POST"])
@role_required("teacher")
def set_status(exam_id):
    from services.exam_pipeline import count_existing_questions

    status = request.form.get("status")
    if status not in ("published", "draft"):
        abort(400)

    def action(cursor, exam):
        if status == "published" and count_existing_questions(cursor, exam_id) == 0:
            raise BuildError("Đề chưa có câu hỏi nên chưa thể xuất bản.")
        cursor.execute("UPDATE exams SET status = %s WHERE id = %s", (status, exam_id))
        return ("Đã xuất bản — học viên đã có thể làm đề này."
                if status == "published" else "Đã chuyển về bản nháp — học viên không còn thấy đề này.")

    return _run(exam_id, action)
