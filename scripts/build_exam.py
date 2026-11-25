"""
TẠO ĐỀ TỰ ĐỘNG BẰNG MỘT LỆNH.

Chuẩn bị trên app:
  1. Admin tạo đề thi (chọn cấp HSK, giáo viên).
  2. Giáo viên tải lên "File đề thi" (PDF). Có thể tải thêm "File đáp án" (PDF/DOCX)
     và "File nghe" (MP3).

Chạy (từ thư mục Cloud_Exam):
  python scripts/build_exam.py --exam-id 3 --dry-run     # xem trước, không ghi gì
  python scripts/build_exam.py --exam-id 3               # tạo thật

Tùy chọn hay dùng:
  --answers "1✓ 2× 6B 7C ..."   nhập đáp án trực tiếp (thay cho file đáp án)
  --replace                      xóa câu hỏi cũ của đề rồi tạo lại
  --ocr always                   bắt buộc OCR (khi lớp chữ trong PDF bị lỗi font)
  --pdf duong_dan.pdf            dùng file PDF trên máy thay vì file trên Supabase
  --update-answers               CHỈ cập nhật đáp án cho đề đã tạo (không xóa câu hỏi,
                                 giữ nguyên chỉnh sửa và bài làm). Dùng kèm --answer-file
                                 hoặc để script tự đọc đáp án trong file đề.

Kết quả trung gian để kiểm tra nằm ở outputs/exam_<id>/.
Sửa tay chỗ OCR sai: tạo data/fixes/exam_<id>.json (cùng dạng data/hsk1_manual_fixes.json).
"""

import sys
import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.exam_pipeline import (  # noqa: E402
    STORAGE_FOLDER,
    get_exam,
    latest_file,
    count_existing_questions,
    has_student_answers,
    update_answers,
    file_text,
    image_content_type,
)
from services.exam_builder import (  # noqa: E402
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


def parse_args():
    p = argparse.ArgumentParser(description="Tạo đề HSK tự động từ file PDF")
    p.add_argument("--exam-id", type=int, required=True)
    p.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi DB / Storage")
    p.add_argument("--replace", action="store_true", help="Xóa câu hỏi cũ rồi tạo lại")
    p.add_argument("--answers", help='Chuỗi đáp án, ví dụ "1✓ 2× 6B 7C"')
    p.add_argument("--pdf", type=Path, help="Dùng file PDF đề trên máy")
    p.add_argument("--answer-file", type=Path, help="Dùng file đáp án (PDF/DOCX) trên máy")
    p.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    p.add_argument("--update-answers", action="store_true",
                   help="Chỉ cập nhật đáp án cho câu hỏi đã có, không xóa/tạo lại câu hỏi")
    p.add_argument("--from-files", nargs=3, metavar=("TEXT", "MANIFEST", "IMAGES_DIR"),
                   help="Dùng lại dữ liệu đã trích trước đó (không đọc PDF)")
    return p.parse_args()


def log(message=""):
    print(message, flush=True)


# ------------------------------------------
# Lấy thông tin đề + file từ DB / Storage
# ------------------------------------------


# ------------------------------------------
# Đọc dữ liệu đã trích (chế độ --from-files)
# ------------------------------------------
def load_from_files(text_path, manifest_path, images_dir):
    import re

    content = Path(text_path).read_text(encoding="utf-8")
    parts = re.split(r"TRANG\s+(\d+)", content)
    pages = [
        {"page": int(parts[i]), "text": parts[i + 1], "source": "file"}
        for i in range(1, len(parts), 2)
    ]

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    images = []
    for item in manifest:
        if item.get("occurrence", 1) != 1:
            continue
        path = Path(images_dir) / item["filename"]
        images.append({
            **{k: item[k] for k in ("page", "filename", "x0", "y0", "x1", "y1")},
            "ext": path.suffix.lstrip("."),
            "data": path.read_bytes() if path.exists() else None,
        })
    return pages, images


# ------------------------------------------
# In tóm tắt
# ------------------------------------------
def print_summary(pages, questions):
    sources = {}
    for page in pages:
        sources.setdefault(page["source"], []).append(page["page"])
    log("Nguồn chữ theo trang: " + ", ".join(f"{k}: {v}" for k, v in sources.items()))
    log()

    for q in questions:
        opts = " ".join(
            f"{label}{'🖼' if o['image'] else ''}{':' + o['text'][:6] if o['text'] else ''}"
            for label, o in q["options"].items()
        )
        mark = "⚠" if q["needs_review"] else "✓"
        answer = q["correct_answer"] or "?"
        if q.get("question_type") in ("fill_blank", "essay"):
            answer = q["options"]["A"]["text"] or "?"
        log(
            f"{mark} Câu {q['question_number']:>2} [{q['section'][:6]}] "
            f"{'🖼 ' if q['question_image'] else ''}{q['question_text'][:18]:<18} "
            f"| {opts} | đáp án: {answer}"
        )

    review = [q for q in questions if q["needs_review"]]
    no_answer = [q["question_number"] for q in questions if not q["correct_answer"]]
    log()
    log(f"Tổng: {len(questions)} câu, {len(review)} câu cần kiểm tra lại.")
    if no_answer:
        log(f"Chưa có đáp án đúng: {len(no_answer)} câu "
            f"(nhập sau trên app bằng ô 'Nhập nhanh đáp án').")


def main():
    args = parse_args()

    from psycopg2.extras import RealDictCursor
    from config.database import get_connection

    out_dir = PROJECT_ROOT / "outputs" / f"exam_{args.exam_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    connection = get_connection()
    storage = None

    def get_storage():
        nonlocal storage
        if storage is None:
            from config.storage import storage as supabase_storage
            storage = supabase_storage
        return storage

    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            exam = get_exam(cursor, args.exam_id)
            level_cfg = load_level_config(exam["level_number"])
            log(f"Đề thi: {exam['title']} (HSK{exam['level_number']})")
            if not level_cfg.get("verified"):
                log("⚠ Cấu hình cấp độ này chưa được kiểm chứng, hãy xem kỹ kết quả --dry-run.")

            existing = count_existing_questions(cursor, args.exam_id)
            if existing and not args.replace and not args.update_answers:
                message = (f"Đề này đã có {existing} câu hỏi. Thêm --replace để xóa và tạo lại "
                           f"(mọi chỉnh sửa giáo viên đã làm trên app sẽ mất).")
                if not args.dry_run:
                    raise BuildError(message)
                log("⚠ " + message)
            if existing and args.replace and has_student_answers(cursor, args.exam_id):
                raise BuildError("Đề này đã có học viên làm bài, không thể xóa để tạo lại. "
                                 "Hãy tạo một đề thi mới trên app rồi chạy với id mới.")

            # ---- 1. Đọc đề ----
            skip_pdf = args.update_answers and (args.answer_file or args.answers)
            if skip_pdf:
                pages, images = [], []
            elif args.from_files:
                pages, images = load_from_files(*args.from_files)
                log("Dùng dữ liệu đã trích sẵn.")
            else:
                if args.pdf:
                    pdf_bytes = args.pdf.read_bytes()
                    log(f"Đọc PDF trên máy: {args.pdf}")
                else:
                    doc = latest_file(cursor, args.exam_id, "exam_document")
                    if not doc:
                        raise BuildError("Đề này chưa có 'File đề thi'. Giáo viên cần tải PDF lên trước.")
                    if not doc["original_filename"].lower().endswith(".pdf"):
                        raise BuildError("File đề thi phải là PDF (DOCX chưa hỗ trợ tạo tự động).")
                    log(f"Tải PDF từ Supabase: {doc['original_filename']}")
                    pdf_bytes = get_storage().download(doc["storage_path"])
                log("Đang đọc chữ và ảnh trong PDF...")
                pages, images = read_pdf(pdf_bytes, ocr=args.ocr)

            # Lưu kết quả trung gian để kiểm tra
            with open(out_dir / ("pages.txt" if pages else "pages_skip.txt"), "w", encoding="utf-8") as f:
                for page in pages:
                    f.write(f"\n{'=' * 50}\nTRANG {page['page']} ({page['source']})\n{'=' * 50}\n")
                    f.write(page["text"])
            image_dir = out_dir / "images"
            image_dir.mkdir(exist_ok=True)
            for img in images:
                if img["data"]:
                    (image_dir / img["filename"]).write_bytes(img["data"])

            # ---- 2. Đáp án ----
            answers, text_answers = {}, {}
            key_text = None
            if args.answers:
                answers = answers_from_text(args.answers)
                log(f"Đáp án nhập trực tiếp: {len(answers)} câu")
            elif args.answer_file:
                key_text = file_text(args.answer_file.read_bytes(), args.answer_file.name, args.ocr)
                source = "file trên máy"
            elif not args.from_files and not skip_pdf:
                key = latest_file(cursor, args.exam_id, "answer_key")
                if key:
                    data = get_storage().download(key["storage_path"])
                    key_text = file_text(data, key["original_filename"], args.ocr)
                    source = f"file '{key['original_filename']}'"
            if key_text is None and not args.answers:
                embedded = embedded_answer_text(pages)
                if embedded:
                    key_text, source = embedded, "trang đáp án trong file đề"
                else:
                    log("Chưa có file đáp án -> giáo viên nhập đáp án sau trên app.")
            if key_text is not None:
                (out_dir / "answer_key.txt").write_text(key_text, encoding="utf-8")
                answers = answers_from_text(key_text)
                text_answers = text_answers_from_text(key_text)
                log(f"Đáp án từ {source}: {len(answers)} câu trắc nghiệm, "
                    f"{len(text_answers)} câu dạng chữ (phần Viết)")

            if args.update_answers:
                if not answers and not text_answers:
                    raise BuildError("Không đọc được đáp án nào. Hãy dùng --answer-file <file đáp án>.")
                count, total, skipped = update_answers(
                    cursor, args.exam_id, answers, text_answers, dry_run=args.dry_run)
                log(f"\nCập nhật đáp án cho {count}/{total} câu.")
                if skipped:
                    log("Bỏ qua (đề không có đáp án này): " + ", ".join(skipped))
                if args.dry_run:
                    log("(dry-run) Chưa ghi gì vào database.")
                    return
                connection.commit()
                log("✅ Đã cập nhật đáp án. Mở 'Quản lý câu hỏi' trên app để kiểm tra.")
                log("Lưu ý: các lượt thi đã nộp TRƯỚC khi có đáp án không tự chấm lại.")
                return

            # ---- 3. Sửa tay (nếu có) ----
            fixes_path = PROJECT_ROOT / "data" / "fixes" / f"exam_{args.exam_id}.json"
            fixes = {}
            if fixes_path.exists():
                fixes = json.loads(fixes_path.read_text(encoding="utf-8"))
                log(f"Áp dụng sửa tay từ {fixes_path.name}")

            # ---- 4. Dựng câu hỏi ----
            questions = build_questions(level_cfg, pages, images, fixes, answers, text_answers)

            with open(out_dir / "questions.json", "w", encoding="utf-8") as f:
                json.dump(questions, f, ensure_ascii=False, indent=4)

            print_summary(pages, questions)
            log(f"File kiểm tra: {out_dir}")

            if args.dry_run:
                log("\n(dry-run) Chưa ghi gì vào database / Storage.")
                return

            # ---- 5. Đưa ảnh lên Supabase Storage ----
            folder = STORAGE_FOLDER.format(exam_id=args.exam_id)
            by_name = {img["filename"]: img for img in images}
            files = used_image_files(questions)
            log(f"\nĐang tải {len(files)} ảnh lên Supabase Storage...")
            for name in files:
                img = by_name[name]
                get_storage().upload(
                    f"{folder}/{name}",
                    img["data"],
                    {"content-type": image_content_type(img["ext"]), "upsert": "true"},
                )

            # ---- 6. Ghi database ----
            save_to_db(
                cursor, args.exam_id, level_cfg, questions,
                image_url=lambda name: f"/media/{folder}/{name}",
                replace=args.replace, log=log,
            )

        connection.commit()
        log(f"\n✅ Đã tạo {len(questions)} câu cho đề '{exam['title']}'.")
        log("Tiếp theo: giáo viên mở 'Quản lý câu hỏi' để kiểm tra các câu ⚠ và nhập đáp án còn thiếu.")

    except BuildError as error:
        connection.rollback()
        log(f"\n❌ {error}")
        sys.exit(1)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
