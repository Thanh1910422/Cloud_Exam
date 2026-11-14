"""
Đưa câu hỏi HSK1 từ outputs/HSK1_questions_final.json vào database
để trang giáo viên / học viên hiển thị được.

Cách chạy (từ thư mục gốc Cloud_Exam):
    python scripts/import_questions_to_db.py --exam-id 1 --dry-run   # xem trước
    python scripts/import_questions_to_db.py --exam-id 1             # ghi thật
    python scripts/import_questions_to_db.py --exam-id 1 --replace   # xóa câu cũ rồi ghi lại

Script sẽ:
  1. Kiểm tra đề thi tồn tại.
  2. Tạo phần thi "listening" và "reading" nếu chưa có.
  3. Copy ảnh vào static/question_images/hsk1/ để Flask phục vụ được.
  4. Thêm câu hỏi vào bảng questions và đáp án vào answer_options.
Tất cả chạy trong 1 transaction: lỗi ở đâu thì không ghi gì cả.
"""

import sys
import json
import shutil
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_INPUT = PROJECT_ROOT / "outputs" / "HSK1_questions_final.json"
DEFAULT_IMAGES_DIR = PROJECT_ROOT / "outputs" / "pdf_images"
STATIC_IMAGE_DIR = PROJECT_ROOT / "static" / "question_images" / "hsk1"
STATIC_URL_PREFIX = "/static/question_images/hsk1"

POINTS_PER_QUESTION = 5  # HSK1: 40 câu, tổng 200 điểm

SECTION_DEFAULTS = {
    "listening": {"title": "听力 - Nghe hiểu", "minutes": 15, "order": 1},
    "reading": {"title": "阅读 - Đọc hiểu", "minutes": 17, "order": 2},
}


def parse_args():
    parser = argparse.ArgumentParser(description="Import câu hỏi HSK1 vào DB")
    parser.add_argument("--exam-id", type=int, required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR,
                        help="Thư mục chứa page_XX_image_YY.jpeg")
    parser.add_argument("--replace", action="store_true",
                        help="Xóa câu hỏi cũ trong phần thi trước khi import")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ in ra, không ghi DB, không copy ảnh")
    return parser.parse_args()


def image_url(filename):
    return f"{STATIC_URL_PREFIX}/{filename}" if filename else None


def collect_images(questions):
    names = set()
    for q in questions:
        if q["question_image"]:
            names.add(q["question_image"])
        for option in q["options"].values():
            if option["image"]:
                names.add(option["image"])
    return sorted(names)


def copy_images(filenames, images_dir):
    missing = [n for n in filenames if not (images_dir / n).exists()]
    if missing:
        raise FileNotFoundError(
            f"Không tìm thấy {len(missing)} ảnh trong {images_dir}, "
            f"ví dụ: {missing[:3]}. Dùng --images-dir để chỉ đúng thư mục."
        )

    STATIC_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for name in filenames:
        shutil.copy2(images_dir / name, STATIC_IMAGE_DIR / name)


def get_or_create_section(cursor, exam_id, section_type):
    cursor.execute("""
        SELECT id FROM exam_sections
        WHERE exam_id = %s AND section_type = %s
    """, (exam_id, section_type))
    row = cursor.fetchone()
    if row:
        return row["id"]

    cfg = SECTION_DEFAULTS[section_type]
    cursor.execute("""
        INSERT INTO exam_sections
            (exam_id, section_type, section_title, time_limit_minutes, sort_order)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (exam_id, section_type, cfg["title"], cfg["minutes"], cfg["order"]))
    return cursor.fetchone()["id"]


def insert_question(cursor, section_id, q):
    cursor.execute("""
        INSERT INTO questions
            (section_id, question_type, question_text, image_url,
             audio_url, points, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        section_id,
        q["question_type"],
        q["question_text"] or "",
        image_url(q["question_image"]),
        None,
        POINTS_PER_QUESTION,
        q["question_number"],
    ))
    question_id = cursor.fetchone()["id"]

    for label, option in q["options"].items():
        cursor.execute("""
            INSERT INTO answer_options
                (question_id, option_label, option_text, is_correct, option_image_url)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            question_id,
            label,
            option["text"] or "",
            label == q["correct_answer"],
            image_url(option["image"]),
        ))

    return question_id


def print_preview(questions):
    for q in questions:
        options = " | ".join(
            f"{label}:{o['text'] or ''}{'[ảnh]' if o['image'] else ''}"
            for label, o in q["options"].items()
        )
        print(
            f"[{q['section']}] Câu {q['question_number']:>2} "
            f"{'[ảnh] ' if q['question_image'] else ''}"
            f"{q['question_text'][:25]} -> {options}"
        )


def main():
    args = parse_args()

    with open(args.input, "r", encoding="utf-8") as file:
        questions = json.load(file)

    images = collect_images(questions)
    print(f"Đọc {len(questions)} câu, {len(images)} ảnh từ {args.input.name}")

    if args.dry_run:
        print_preview(questions)
        print("\n(dry-run) Không ghi gì vào DB.")
        return

    from psycopg2.extras import RealDictCursor
    from config.database import get_connection

    copy_images(images, args.images_dir)
    print(f"Đã copy ảnh vào {STATIC_IMAGE_DIR}")

    connection = get_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, title FROM exams WHERE id = %s",
                           (args.exam_id,))
            exam = cursor.fetchone()
            if not exam:
                raise ValueError(f"Không có đề thi id={args.exam_id}")
            print(f"Đề thi: {exam['title']}")

            section_ids = {
                s: get_or_create_section(cursor, args.exam_id, s)
                for s in ("listening", "reading")
            }

            for section_type, section_id in section_ids.items():
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM questions WHERE section_id = %s",
                    (section_id,))
                existing = cursor.fetchone()["n"]

                if existing and not args.replace:
                    raise ValueError(
                        f"Phần {section_type} đã có {existing} câu. "
                        f"Thêm --replace nếu muốn xóa và import lại."
                    )
                if existing:
                    cursor.execute("""
                        DELETE FROM answer_options WHERE question_id IN
                            (SELECT id FROM questions WHERE section_id = %s)
                    """, (section_id,))
                    cursor.execute(
                        "DELETE FROM questions WHERE section_id = %s",
                        (section_id,))
                    print(f"Đã xóa {existing} câu cũ của phần {section_type}")

            for q in questions:
                insert_question(cursor, section_ids[q["section"]], q)

        connection.commit()
        print(f"Đã import {len(questions)} câu vào đề thi {args.exam_id}.")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
