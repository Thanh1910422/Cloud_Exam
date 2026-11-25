"""
Khu vực học viên: xem đề, làm bài, nộp bài, chấm điểm tự động, xem kết quả.

Đường dẫn:
    /student/exams/                         Danh sách đề đã publish + lịch sử thi
    /student/exams/<exam_id>/start  (POST)  Bắt đầu (hoặc làm tiếp) một lượt thi
    /student/exams/attempts/<id>            Trang làm bài
    /student/exams/attempts/<id>/submit     Nộp bài + chấm điểm (POST)
    /student/exams/attempts/<id>/result     Xem kết quả
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

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


student_exam_bp = Blueprint(
    "student_exam",
    __name__,
    url_prefix="/student/exams"
)

# Câu học viên tự gõ chữ: fill_blank (máy chấm theo đáp án), essay (giáo viên chấm)
TYPED_TYPES = ("fill_blank", "essay")

# Cho phép nộp trễ vài phút (mạng chậm, JS tự nộp khi hết giờ)
SUBMIT_GRACE = timedelta(minutes=2)
AUDIO_LINK_SECONDS = 3 * 60 * 60


# ==========================================
# HÀM DÙNG CHUNG
# ==========================================
def get_own_attempt(cursor, attempt_id):
    """Lấy lượt thi kèm thông tin đề, chỉ khi lượt thi thuộc học viên này."""
    cursor.execute("""
        SELECT
            exam_attempts.*,
            exams.title AS exam_title,
            exams.duration_minutes,
            hsk_levels.level_name
        FROM exam_attempts
        JOIN exams ON exam_attempts.exam_id = exams.id
        JOIN hsk_levels ON exams.level_id = hsk_levels.id
        WHERE exam_attempts.id = %s
          AND exam_attempts.student_id = %s
    """, (attempt_id, session.get("user_id")))

    return cursor.fetchone()


def deadline_of(attempt):
    return attempt["started_at"] + timedelta(minutes=attempt["duration_minutes"])


def load_exam_content(cursor, exam_id, with_answers=False):
    """
    Lấy các phần thi -> câu hỏi -> đáp án.
    with_answers=False: KHÔNG lấy cột is_correct (trang làm bài không lộ đáp án).
    """
    cursor.execute("""
        SELECT id, section_type, section_title, time_limit_minutes
        FROM exam_sections
        WHERE exam_id = %s
        ORDER BY sort_order, id
    """, (exam_id,))
    sections = cursor.fetchall()

    correct_column = ", is_correct" if with_answers else ""

    for section in sections:
        cursor.execute("""
            SELECT id, question_type, question_text, image_url,
                   audio_url, points, sort_order
            FROM questions
            WHERE section_id = %s
            ORDER BY sort_order, id
        """, (section["id"],))
        section["questions"] = cursor.fetchall()

        for question in section["questions"]:
            if not with_answers and question["question_type"] in TYPED_TYPES:
                question["options"] = []      # câu gõ chữ: không gửi đáp án xuống trình duyệt
                continue
            cursor.execute(f"""
                SELECT id, option_label, option_text, option_image_url
                       {correct_column}
                FROM answer_options
                WHERE question_id = %s
                ORDER BY option_label
            """, (question["id"],))
            question["options"] = cursor.fetchall()

    return sections


def get_listening_audio_url(cursor, exam_id):
    """Link tạm thời tới file nghe mới nhất mà giáo viên đã tải lên."""
    cursor.execute("""
        SELECT storage_path
        FROM exam_files
        WHERE exam_id = %s AND file_type = 'listening_audio'
        ORDER BY id DESC
        LIMIT 1
    """, (exam_id,))
    row = cursor.fetchone()

    if not row:
        return None

    try:
        from config.storage import storage

        result = storage.create_signed_url(row["storage_path"], AUDIO_LINK_SECONDS)
        # Tên khóa khác nhau giữa các phiên bản thư viện supabase
        return result.get("signedURL") or result.get("signedUrl")
    except Exception:
        current_app.logger.exception("Cannot create audio signed URL")
        return None


def normalize_answer(text):
    """Bỏ khoảng trắng và dấu câu để so sánh: '弟弟 高兴地笑了。' == '弟弟高兴地笑了'."""
    import re
    return re.sub(r"[\s。．.，,！!？?、；;：:“”\"'（）()\-–—→>]", "", text or "").upper()


def typed_answer_correct(answer_text, options):
    """Đúng nếu khớp một đáp án đúng; đáp án có thể ghi nhiều cách, ngăn bởi '/'."""
    import re
    given = normalize_answer(answer_text)
    if not given:
        return False
    for option in options:
        if not option.get("is_correct"):
            continue
        for accepted in re.split(r"[/／|]", option["option_text"] or ""):
            if accepted.strip() and normalize_answer(accepted) == given:
                return True
    return False


# ==========================================
# DANH SÁCH ĐỀ THI + LỊCH SỬ
# ==========================================
@student_exam_bp.route("/")
@role_required("student")
def exams():
    connection = None
    try:
        level = int(request.args.get("level", ""))
        level = level if 1 <= level <= 6 else None
    except ValueError:
        level = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT
                    exams.id,
                    exams.title,
                    exams.description,
                    exams.duration_minutes,
                    hsk_levels.level_name,
                    COUNT(questions.id) AS question_count
                FROM exams
                JOIN hsk_levels ON exams.level_id = hsk_levels.id
                LEFT JOIN exam_sections ON exam_sections.exam_id = exams.id
                LEFT JOIN questions ON questions.section_id = exam_sections.id
                WHERE exams.status = 'published'
                  AND (%s::int IS NULL OR hsk_levels.level_number = %s::int)
                GROUP BY exams.id, hsk_levels.level_name, hsk_levels.level_number
                HAVING COUNT(questions.id) > 0
                ORDER BY hsk_levels.level_number, exams.title
            """, (level, level))
            exam_list = cursor.fetchall()

            cursor.execute("""
                SELECT
                    exam_attempts.id,
                    exam_attempts.status,
                    exam_attempts.started_at,
                    exam_attempts.submitted_at,
                    exam_attempts.listening_score,
                    exam_attempts.reading_score,
                    exam_attempts.writing_score,
                    exam_attempts.total_score,
                    exams.title AS exam_title
                FROM exam_attempts
                JOIN exams ON exam_attempts.exam_id = exams.id
                WHERE exam_attempts.student_id = %s
                ORDER BY exam_attempts.started_at DESC
                LIMIT 30
            """, (session.get("user_id"),))
            attempts = cursor.fetchall()

        return render_template(
            "student/exams.html",
            exams=exam_list,
            attempts=attempts,
            current_level=level,
            tab_endpoint="student_exam.exams"
        )

    except Exception:
        current_app.logger.exception("Cannot load student exams")
        flash("Không thể tải danh sách đề thi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()


# ==========================================
# BẮT ĐẦU / LÀM TIẾP
# ==========================================
@student_exam_bp.route("/<int:exam_id>/start", methods=["POST"])
@role_required("student")
def start_exam(exam_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, duration_minutes
                FROM exams
                WHERE id = %s AND status = 'published'
            """, (exam_id,))
            exam = cursor.fetchone()

            if not exam:
                abort(404)

            # Còn lượt đang làm dở và chưa hết giờ -> làm tiếp
            cursor.execute("""
                SELECT id, started_at
                FROM exam_attempts
                WHERE exam_id = %s
                  AND student_id = %s
                  AND status = 'in_progress'
                ORDER BY started_at DESC
                LIMIT 1
            """, (exam_id, session.get("user_id")))
            existing = cursor.fetchone()

            now = datetime.now(timezone.utc)
            if existing:
                deadline = existing["started_at"] + timedelta(
                    minutes=exam["duration_minutes"]
                ) + SUBMIT_GRACE
                if now <= deadline:
                    return redirect(url_for(
                        "student_exam.take_exam", attempt_id=existing["id"]
                    ))

            cursor.execute("""
                INSERT INTO exam_attempts (exam_id, student_id)
                VALUES (%s, %s)
                RETURNING id
            """, (exam_id, session.get("user_id")))
            attempt_id = cursor.fetchone()["id"]

        connection.commit()

        return redirect(url_for("student_exam.take_exam", attempt_id=attempt_id))

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot start exam")
        flash("Không thể bắt đầu bài thi.", "error")
        return redirect(url_for("student_exam.exams"))

    finally:
        if connection:
            connection.close()


# ==========================================
# TRANG LÀM BÀI
# ==========================================
@student_exam_bp.route("/attempts/<int:attempt_id>")
@role_required("student")
def take_exam(attempt_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            attempt = get_own_attempt(cursor, attempt_id)

            if not attempt:
                abort(404)

            if attempt["status"] != "in_progress":
                return redirect(url_for(
                    "student_exam.result", attempt_id=attempt_id
                ))

            sections = load_exam_content(cursor, attempt["exam_id"])
            audio_url = get_listening_audio_url(cursor, attempt["exam_id"])

        remaining = int(
            (deadline_of(attempt) - datetime.now(timezone.utc)).total_seconds()
        )

        return render_template(
            "student/take_exam.html",
            attempt=attempt,
            sections=sections,
            audio_url=audio_url,
            remaining_seconds=max(remaining, 0)
        )

    except HTTPException:
        raise

    except Exception:
        current_app.logger.exception("Cannot load exam for student")
        flash("Không thể tải bài thi.", "error")
        return redirect(url_for("student_exam.exams"))

    finally:
        if connection:
            connection.close()


# ==========================================
# NỘP BÀI + CHẤM ĐIỂM
# ==========================================
@student_exam_bp.route("/attempts/<int:attempt_id>/submit", methods=["POST"])
@role_required("student")
def submit_exam(attempt_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            attempt = get_own_attempt(cursor, attempt_id)

            if not attempt:
                abort(404)

            if attempt["status"] != "in_progress":
                flash("Bài thi này đã được nộp.", "error")
                return redirect(url_for(
                    "student_exam.result", attempt_id=attempt_id
                ))

            late = datetime.now(timezone.utc) > deadline_of(attempt) + SUBMIT_GRACE

            sections = load_exam_content(
                cursor, attempt["exam_id"], with_answers=True
            )

            scores = {"listening": Decimal(0), "reading": Decimal(0), "writing": Decimal(0)}
            needs_manual = False

            for section in sections:
                for question in section["questions"]:
                    field = f"q_{question['id']}"
                    selected_id = None
                    answer_text = None
                    is_correct = None
                    awarded = Decimal(0)

                    if question["question_type"] == "essay":
                        answer_text = request.form.get(field, "").strip()[:5000] or None
                        needs_manual = needs_manual or bool(answer_text)
                    elif question["question_type"] == "fill_blank":
                        answer_text = request.form.get(field, "").strip()[:500] or None
                        is_correct = (not late) and typed_answer_correct(
                            answer_text, question["options"]
                        )
                        if is_correct:
                            awarded = Decimal(question["points"])
                    else:
                        raw = request.form.get(field, "")
                        options = {str(o["id"]): o for o in question["options"]}
                        chosen = None if late else options.get(raw)

                        if chosen:
                            selected_id = chosen["id"]
                            is_correct = bool(chosen["is_correct"])
                        else:
                            is_correct = False

                        if is_correct:
                            awarded = Decimal(question["points"])

                    if section["section_type"] in scores:
                        scores[section["section_type"]] += awarded

                    cursor.execute("""
                        INSERT INTO student_answers (
                            attempt_id, question_id, selected_option_id,
                            answer_text, is_correct, awarded_points, graded_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (attempt_id, question_id) DO UPDATE SET
                            selected_option_id = EXCLUDED.selected_option_id,
                            answer_text = EXCLUDED.answer_text,
                            is_correct = EXCLUDED.is_correct,
                            awarded_points = EXCLUDED.awarded_points,
                            graded_at = NOW()
                    """, (
                        attempt_id, question["id"], selected_id,
                        answer_text, is_correct, awarded
                    ))

            total = scores["listening"] + scores["reading"] + scores["writing"]

            cursor.execute("""
                UPDATE exam_attempts
                SET status = %s,
                    submitted_at = NOW(),
                    listening_score = %s,
                    reading_score = %s,
                    writing_score = %s,
                    total_score = %s
                WHERE id = %s
            """, (
                "submitted" if needs_manual else "graded",
                scores["listening"],
                scores["reading"],
                scores["writing"],
                total,
                attempt_id
            ))

        connection.commit()

        if late:
            flash("Bài nộp sau khi hết giờ nên không được tính điểm.", "error")
        else:
            flash("Nộp bài thành công!", "success")

        return redirect(url_for("student_exam.result", attempt_id=attempt_id))

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception:
        if connection:
            connection.rollback()
        current_app.logger.exception("Cannot submit exam")
        flash("Không thể nộp bài. Vui lòng thử lại.", "error")
        return redirect(url_for("student_exam.take_exam", attempt_id=attempt_id))

    finally:
        if connection:
            connection.close()


# ==========================================
# KẾT QUẢ
# ==========================================
@student_exam_bp.route("/attempts/<int:attempt_id>/result")
@role_required("student")
def result(attempt_id):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            attempt = get_own_attempt(cursor, attempt_id)

            if not attempt:
                abort(404)

            if attempt["status"] == "in_progress":
                return redirect(url_for(
                    "student_exam.take_exam", attempt_id=attempt_id
                ))

            sections = load_exam_content(
                cursor, attempt["exam_id"], with_answers=True
            )

            cursor.execute("""
                SELECT student_answers.question_id, selected_option_id, answer_text,
                       is_correct, awarded_points,
                       writing_scores.id AS teacher_graded, writing_scores.feedback
                FROM student_answers
                LEFT JOIN writing_scores
                    ON writing_scores.attempt_id = student_answers.attempt_id
                   AND writing_scores.question_id = student_answers.question_id
                WHERE student_answers.attempt_id = %s
            """, (attempt_id,))
            answers = {row["question_id"]: row for row in cursor.fetchall()}

        max_scores = {
            s["section_type"]: sum(q["points"] for q in s["questions"])
            for s in sections
        }
        max_total = sum(max_scores.values())
        # HSK1, HSK2: đạt khi được >= 60% tổng điểm (120/200)
        passed = (
            max_total > 0
            and Decimal(attempt["total_score"] or 0) >= Decimal(max_total) * Decimal("0.6")
        )
        correct_count = sum(1 for a in answers.values() if a["is_correct"])
        question_count = sum(len(s["questions"]) for s in sections)

        return render_template(
            "student/result.html",
            attempt=attempt,
            sections=sections,
            answers=answers,
            max_scores=max_scores,
            max_total=max_total,
            passed=passed,
            correct_count=correct_count,
            question_count=question_count
        )

    except HTTPException:
        raise

    except Exception:
        current_app.logger.exception("Cannot load exam result")
        flash("Không thể tải kết quả.", "error")
        return redirect(url_for("student_exam.exams"))

    finally:
        if connection:
            connection.close()
