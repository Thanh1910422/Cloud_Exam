"""
Quy trình tạo đề dùng chung cho:
  - lệnh trên máy:  python scripts/build_exam.py --exam-id N
  - nút trên web:   giáo viên bấm "Tạo câu hỏi" / "Cập nhật đáp án"

Mọi file (PDF đề, file đáp án, ảnh câu hỏi) nằm trên Supabase Storage.
"""

import io
import re

from services.exam_builder import (
    BuildError,
    load_level_config,
    read_pdf,
    build_questions,
    answers_from_text,
    text_answers_from_text,
    embedded_answer_text,
    save_to_db,
    used_image_files,
)

STORAGE_FOLDER = "exams/{exam_id}/question_images/auto"


# ==========================================
# THÔNG TIN ĐỀ + FILE
# ==========================================
def get_exam(cursor, exam_id):
    cursor.execute("""
        SELECT exams.id, exams.title, exams.status, exams.teacher_id,
               hsk_levels.level_number
        FROM exams JOIN hsk_levels ON exams.level_id = hsk_levels.id
        WHERE exams.id = %s
    """, (exam_id,))
    exam = cursor.fetchone()
    if not exam:
        raise BuildError(f"Không có đề thi id={exam_id}")
    return exam


def latest_file(cursor, exam_id, file_type):
    cursor.execute("""
        SELECT storage_path, original_filename
        FROM exam_files
        WHERE exam_id = %s AND file_type = %s
        ORDER BY id DESC
        LIMIT 1
    """, (exam_id, file_type))
    return cursor.fetchone()


def count_existing_questions(cursor, exam_id):
    cursor.execute("""
        SELECT COUNT(*) AS n
        FROM questions JOIN exam_sections ON questions.section_id = exam_sections.id
        WHERE exam_sections.exam_id = %s
    """, (exam_id,))
    return cursor.fetchone()["n"]


def has_student_answers(cursor, exam_id):
    cursor.execute("SELECT COUNT(*) AS n FROM exam_attempts WHERE exam_id = %s", (exam_id,))
    return cursor.fetchone()["n"] > 0


def file_text(data, filename, ocr="auto"):
    """Lấy chữ từ file đáp án PDF, DOCX hoặc TXT."""
    name = (filename or "").lower()
    if name.endswith(".txt"):
        return data.decode("utf-8-sig")
    if name.endswith(".docx"):
        import docx
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append("  ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    pages, _ = read_pdf(data, ocr=ocr)
    return "\n".join(p["text"] for p in pages)


def image_content_type(ext):
    return f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"


# ==========================================
# ĐÁP ÁN
# ==========================================
def read_answer_key(cursor, storage, exam_id, pages=None, ocr="auto", log=print):
    """
    Đáp án lấy theo thứ tự ưu tiên: file 'Đáp án' giáo viên tải lên,
    rồi tới trang đáp án nằm cuối file đề. Trả về (answers, text_answers, nguồn).
    """
    key = latest_file(cursor, exam_id, "answer_key")
    if key:
        text = file_text(storage.download(key["storage_path"]), key["original_filename"], ocr)
        source = f"file đáp án '{key['original_filename']}'"
    else:
        text = embedded_answer_text(pages or [])
        source = "trang đáp án trong file đề" if text else None

    if not text:
        return {}, {}, None
    return answers_from_text(text), text_answers_from_text(text), source


def update_answers(cursor, exam_id, answers, text_answers, dry_run=False):
    """Ghi đáp án vào câu hỏi đã có (theo số câu = sort_order). Trả về (số câu, tổng, bỏ qua)."""
    cursor.execute("""
        SELECT questions.id, questions.sort_order, questions.question_type
        FROM questions
        JOIN exam_sections ON questions.section_id = exam_sections.id
        WHERE exam_sections.exam_id = %s
    """, (exam_id,))
    by_number = {q["sort_order"]: q for q in cursor.fetchall()}
    if not by_number:
        raise BuildError("Đề này chưa có câu hỏi. Hãy tạo câu hỏi trước.")

    updated, skipped = 0, []
    for number, q in sorted(by_number.items()):
        if q["question_type"] == "multiple_choice":
            label = answers.get(number)
            if not label:
                continue
            cursor.execute(
                "SELECT 1 FROM answer_options WHERE question_id = %s AND option_label = %s",
                (q["id"], label))
            if not cursor.fetchone():
                skipped.append(f"{number}{label}")
                continue
            if not dry_run:
                cursor.execute("""
                    UPDATE answer_options SET is_correct = (option_label = %s)
                    WHERE question_id = %s
                """, (label, q["id"]))
            updated += 1
        else:
            text = text_answers.get(number)
            if not text:
                continue
            if not dry_run:
                cursor.execute("""
                    INSERT INTO answer_options (question_id, option_label, option_text, is_correct)
                    VALUES (%s, 'A', %s, TRUE)
                    ON CONFLICT (question_id, option_label) DO UPDATE SET
                        option_text = EXCLUDED.option_text, is_correct = TRUE
                """, (q["id"], text))
            updated += 1
    return updated, len(by_number), skipped


# ==========================================
# TẠO CÂU HỎI TỪ FILE ĐỀ TRÊN STORAGE (dùng cho nút trên web)
# ==========================================
def build_from_storage(cursor, storage, exam_id, replace=False, log=print):
    """
    Tải PDF đề mới nhất của đề thi từ Storage -> tạo câu hỏi -> đưa ảnh lên Storage
    -> ghi DB (chưa commit). Trả về dict tóm tắt để hiện cho giáo viên.
    """
    exam = get_exam(cursor, exam_id)
    level_cfg = load_level_config(exam["level_number"])

    existing = count_existing_questions(cursor, exam_id)
    if existing and not replace:
        raise BuildError(f"Đề này đã có {existing} câu hỏi. Chọn 'Tạo lại từ đầu' nếu muốn thay thế.")
    if existing and has_student_answers(cursor, exam_id):
        raise BuildError("Đề này đã có học viên làm bài nên không thể tạo lại. Hãy tạo một đề thi mới.")

    doc = latest_file(cursor, exam_id, "exam_document")
    if not doc:
        raise BuildError("Chưa có file đề thi. Hãy tải file PDF đề lên trước.")
    if not doc["original_filename"].lower().endswith(".pdf"):
        raise BuildError("File đề thi phải là PDF để tạo câu hỏi tự động.")

    log(f"Đọc file đề: {doc['original_filename']}")
    pages, images = read_pdf(storage.download(doc["storage_path"]), ocr="auto")

    text_chars = sum(len(re.sub(r"\s", "", p["text"])) for p in pages)
    chinese_chars = sum(len(re.findall(r"[\u4e00-\u9fff]", p["text"])) for p in pages)
    if text_chars < 200 or chinese_chars < 100:
        raise BuildError(
            "File PDF này không có lớp chữ Hán đọc được (PDF dạng scan, hoặc chữ Hán được vẽ thành hình). "
            "Web không đọc được loại này. Hãy chạy trên máy đã cài Tesseract: "
            f"python scripts/build_exam.py --exam-id {exam_id} --ocr always"
        )

    answers, text_answers, source = read_answer_key(cursor, storage, exam_id, pages, log=log)

    questions = build_questions(level_cfg, pages, images, None, answers, text_answers)

    folder = STORAGE_FOLDER.format(exam_id=exam_id)
    by_name = {img["filename"]: img for img in images}
    files = used_image_files(questions)
    for name in files:
        img = by_name[name]
        storage.upload(f"{folder}/{name}", img["data"],
                       {"content-type": image_content_type(img["ext"]), "upsert": "true"})

    save_to_db(cursor, exam_id, level_cfg, questions,
               image_url=lambda name: f"/media/{folder}/{name}",
               replace=replace, log=log)

    return {
        "questions": len(questions),
        "images": len(files),
        "needs_review": sum(1 for q in questions if q["needs_review"]),
        "with_answer": sum(1 for q in questions if q["correct_answer"]),
        "answer_source": source,
        "level": exam["level_number"],
    }


def update_answers_from_storage(cursor, storage, exam_id, log=print):
    """Nút 'Cập nhật đáp án': đọc file đáp án (hoặc trang đáp án trong file đề) rồi ghi vào DB."""
    pages = None
    if not latest_file(cursor, exam_id, "answer_key"):
        doc = latest_file(cursor, exam_id, "exam_document")
        if doc and doc["original_filename"].lower().endswith(".pdf"):
            pages, _ = read_pdf(storage.download(doc["storage_path"]), ocr="auto")

    answers, text_answers, source = read_answer_key(cursor, storage, exam_id, pages, log=log)
    if not source:
        raise BuildError("Không tìm thấy đáp án: hãy tải 'File đáp án' lên, "
                         "hoặc dùng file đề có trang đáp án (答案) ở cuối.")
    if not answers and not text_answers:
        raise BuildError(f"Không đọc được đáp án nào từ {source}.")

    updated, total, skipped = update_answers(cursor, exam_id, answers, text_answers)
    return {"updated": updated, "total": total, "skipped": skipped, "source": source}
