
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

            # File mới nhất của từng loại (đề, file nghe, đáp án)
            cursor.execute("""
                SELECT DISTINCT ON (file_type)
                    file_type, original_filename, size_bytes
                FROM exam_files
                WHERE exam_id = %s
                ORDER BY file_type, id DESC
            """, (exam_id,))
            files = {row["file_type"]: row for row in cursor.fetchall()}

            cursor.execute("""
                SELECT
                    COUNT(*) AS questions,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM answer_options
                        WHERE answer_options.question_id = questions.id
                          AND answer_options.is_correct
                    )) AS with_answer
                FROM questions
                JOIN exam_sections ON questions.section_id = exam_sections.id
                WHERE exam_sections.exam_id = %s
            """, (exam_id,))
            counts = cursor.fetchone()

            cursor.execute(
                "SELECT COUNT(*) AS n FROM exam_attempts WHERE exam_id = %s",
                (exam_id,))
            attempts = cursor.fetchone()["n"]

            cursor.execute("""
                SELECT hsk_levels.level_number FROM exams
                JOIN hsk_levels ON exams.level_id = hsk_levels.id WHERE exams.id = %s
            """, (exam_id,))
            level_number = cursor.fetchone()["level_number"]

        from routes.teacher_builder import supported_levels

        return render_template(
            "teacher/exam_detail.html",
            exam=exam,
            sections=sections,
            files=files,
            counts=counts,
            attempts=attempts,
            auto_supported=level_number in supported_levels()
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
                        option_image_url,
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


# ==========================================
# HÀM DÙNG CHUNG: LẤY CÂU HỎI CỦA GIÁO VIÊN
# ==========================================
def get_owned_question(cursor, question_id):
    """Chỉ trả về câu hỏi nếu nó thuộc đề thi của giáo viên đang đăng nhập."""
    cursor.execute("""
        SELECT
            questions.id,
            questions.section_id,
            questions.question_type,
            questions.question_text,
            questions.image_url,
            questions.points,
            questions.sort_order,
            exam_sections.section_title,
            exams.title AS exam_title
        FROM questions
        JOIN exam_sections ON questions.section_id = exam_sections.id
        JOIN exams ON exam_sections.exam_id = exams.id
        WHERE questions.id = %s
          AND exams.teacher_id = %s
    """, (question_id, session.get("user_id")))

    return cursor.fetchone()


# ==========================================
# SỬA MỘT CÂU HỎI + CHỌN ĐÁP ÁN ĐÚNG
# ==========================================
@teacher_questions_bp.route(
    "/questions/<int:question_id>/edit",
    methods=["GET", "POST"]
)
@role_required("teacher")
def edit_question(question_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            question = get_owned_question(cursor, question_id)

            if not question:
                abort(404)

            cursor.execute("""
                SELECT id, option_label, option_text, option_image_url, is_correct
                FROM answer_options
                WHERE question_id = %s
                ORDER BY option_label
            """, (question_id,))
            options = cursor.fetchall()

            # Câu dạng ghép A-F mà còn thiếu nhãn -> cho phép thêm
            existing = {o["option_label"] for o in options}
            missing_labels = []
            # (câu Đúng/Sai có A-B, câu tranh có A-C thì không cần thêm)
            typed = question["question_type"] in ("fill_blank", "essay")
            if typed and not options:
                missing_labels = ["A"]      # câu Viết: một ô đáp án đúng
            elif not typed and (len(options) < 2 or any(l > "C" for l in existing)):
                missing_labels = [l for l in "ABCDEF" if l not in existing]

            if request.method == "POST":
                question_text = request.form.get("question_text", "").strip()
                correct_label = request.form.get("correct_label", "").strip()

                try:
                    points = float(request.form.get("points", "0"))
                    if points < 0:
                        raise ValueError
                except ValueError:
                    flash("Điểm phải là số không âm.", "error")
                    return redirect(url_for(
                        "teacher_questions.edit_question",
                        question_id=question_id
                    ))

                if typed:
                    # câu Viết: có nhập đáp án thì đáp án A là đáp án đúng
                    answer = (request.form.get(f"option_{options[0]['id']}", "") if options
                              else request.form.get("new_option_A", "")).strip()
                    correct_label = "A" if answer else ""

                valid_labels = existing | set(missing_labels)
                if correct_label and correct_label not in valid_labels:
                    flash("Đáp án đúng không hợp lệ.", "error")
                    return redirect(url_for(
                        "teacher_questions.edit_question",
                        question_id=question_id
                    ))

                cursor.execute("""
                    UPDATE questions
                    SET question_text = %s, points = %s
                    WHERE id = %s
                """, (question_text, points, question_id))

                for option in options:
                    new_text = request.form.get(
                        f"option_{option['id']}", ""
                    ).strip()

                    cursor.execute("""
                        UPDATE answer_options
                        SET option_text = %s, is_correct = %s
                        WHERE id = %s
                    """, (
                        new_text,
                        option["option_label"] == correct_label,
                        option["id"]
                    ))

                for label in missing_labels:
                    new_text = request.form.get(f"new_option_{label}", "").strip()
                    if not new_text and label != correct_label:
                        continue  # bỏ trống thì không tạo
                    cursor.execute("""
                        INSERT INTO answer_options
                            (question_id, option_label, option_text, is_correct)
                        VALUES (%s, %s, %s, %s)
                    """, (question_id, label, new_text, label == correct_label))

                # Dùng chung các đáp án A-F cho nhiều câu (vd câu 31-35 của HSK 1)
                shared_message = ""
                if not typed and request.form.get("apply_shared"):
                    try:
                        range_from = int(request.form.get("shared_from", ""))
                        range_to = int(request.form.get("shared_to", ""))
                    except ValueError:
                        range_from = range_to = None
                    if range_from is None or range_from > range_to:
                        connection.rollback()
                        flash("Khoảng câu áp dụng không hợp lệ.", "error")
                        return redirect(url_for(
                            "teacher_questions.edit_question", question_id=question_id
                        ))

                    shared = {}
                    for option in options:
                        shared[option["option_label"]] = request.form.get(
                            f"option_{option['id']}", "").strip()
                    for label in missing_labels:
                        shared[label] = request.form.get(f"new_option_{label}", "").strip()
                    shared = {label: text for label, text in shared.items() if text}

                    cursor.execute("""
                        SELECT id FROM questions
                        WHERE section_id = %s
                          AND question_type = 'multiple_choice'
                          AND sort_order BETWEEN %s AND %s
                          AND id <> %s
                    """, (question["section_id"], range_from, range_to, question_id))
                    others = [row["id"] for row in cursor.fetchall()]

                    for other_id in others:
                        for label, text in shared.items():
                            # giữ nguyên đáp án đúng và ảnh của từng câu, chỉ thay nội dung chữ
                            cursor.execute("""
                                INSERT INTO answer_options
                                    (question_id, option_label, option_text, is_correct)
                                VALUES (%s, %s, %s, FALSE)
                                ON CONFLICT (question_id, option_label)
                                DO UPDATE SET option_text = EXCLUDED.option_text
                            """, (other_id, label, text))
                    shared_message = (f" Đã áp dụng đáp án {''.join(sorted(shared))} "
                                      f"cho {len(others)} câu khác ({range_from}–{range_to}).")

                connection.commit()
                flash(f"Đã lưu câu {question['sort_order']}.{shared_message}", "success")

                return redirect(url_for(
                    "teacher_questions.section_questions",
                    section_id=question["section_id"]
                ) + f"#q{question_id}")

        all_labels = existing | set(missing_labels)
        shared_bank = not typed and any(label > "C" for label in all_labels)
        return render_template(
            "teacher/edit_question.html",
            question=question,
            options=options,
            missing_labels=missing_labels,
            typed=typed,
            shared_bank=shared_bank
        )

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot edit question")
        flash("Không thể lưu câu hỏi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()


# ==========================================
# NHẬP NHANH ĐÁP ÁN CẢ PHẦN THI
# Ví dụ: "1✓ 2× 3✓ 6B 7C 11F" hoặc "21.A 22.B"
# ==========================================
from services.answer_key import parse_answer_key  # noqa: E402


@teacher_questions_bp.route(
    "/sections/<int:section_id>/answer-key",
    methods=["POST"]
)
@role_required("teacher")
def import_answer_key(section_id):
    connection = None
    back = url_for("teacher_questions.section_questions", section_id=section_id)

    answers = parse_answer_key(request.form.get("answer_key", ""))

    if not answers:
        flash("Không đọc được đáp án nào. Ví dụ: 1✓ 2× 6B 7C", "error")
        return redirect(back)

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT exam_sections.id
                FROM exam_sections
                JOIN exams ON exam_sections.exam_id = exams.id
                WHERE exam_sections.id = %s AND exams.teacher_id = %s
            """, (section_id, session.get("user_id")))

            if not cursor.fetchone():
                abort(404)

            updated, skipped = 0, []

            for number, label in sorted(answers.items()):
                cursor.execute("""
                    SELECT id
                    FROM questions
                    WHERE section_id = %s AND sort_order = %s
                """, (section_id, number))
                row = cursor.fetchone()

                if not row:
                    skipped.append(f"{number}{label}")
                    continue

                # Đáp án chưa có (OCR đọc thiếu) -> tạo mới, nội dung để trống
                cursor.execute("""
                    INSERT INTO answer_options
                        (question_id, option_label, option_text, is_correct)
                    VALUES (%s, %s, '', FALSE)
                    ON CONFLICT (question_id, option_label) DO NOTHING
                """, (row["id"], label))

                cursor.execute("""
                    UPDATE answer_options
                    SET is_correct = (option_label = %s)
                    WHERE question_id = %s
                """, (label, row["id"]))
                updated += 1

        connection.commit()

        flash(f"Đã cập nhật đáp án cho {updated} câu.", "success")
        if skipped:
            flash(
                "Bỏ qua (không có số câu này trong phần thi): "
                + ", ".join(skipped),
                "error"
            )

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot import answer key")
        flash("Không thể nhập đáp án.", "error")

    finally:
        if connection:
            connection.close()

    return redirect(back)
