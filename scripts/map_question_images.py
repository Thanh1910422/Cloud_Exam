"""
Ghép ảnh trích xuất từ PDF vào đúng câu hỏi / đáp án của đề HSK1.

Sửa so với bản cũ:
- Sắp xếp ảnh theo HÀNG (gom các ảnh có y0 gần nhau) rồi mới theo x0.
  Bản cũ sort theo (y0, x0) nên khi y0 lệch vài pixel thì thứ tự A-B-C bị đảo
  (câu 7, 9, 10 bị sai).
- Thêm trang 3 (câu 1-5) và trang 9 (câu 26-30).
- Trang 6 và trang 9 là dạng "chọn tranh A-F dùng chung": 6 ảnh là 6 đáp án
  A-F cho tất cả các câu, không phải mỗi câu 1 ảnh.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_FILE = PROJECT_ROOT / "outputs" / "image_manifest.json"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "question_image_mapping.json"

# Hai ảnh có |y0| chênh nhau nhỏ hơn ngưỡng này được coi là cùng một hàng
ROW_TOLERANCE = 30


# Cấu hình bố cục từng trang
#   per_question : mỗi câu có 1 ảnh (ảnh nằm ở câu hỏi)
#   per_option   : mỗi câu có 3 ảnh A, B, C (mỗi hàng là một câu)
#   shared       : các ảnh là đáp án A-F dùng chung cho nhiều câu
PAGE_LAYOUTS = {
    3: {"mode": "per_question", "skip": 2, "questions": [1, 2, 3, 4, 5]},
    4: {"mode": "per_option", "skip": 3, "questions": [6, 7, 8]},
    5: {"mode": "per_option", "skip": 0, "questions": [9, 10]},
    6: {"mode": "shared", "skip": 0, "questions": [11, 12, 13, 14, 15]},
    8: {"mode": "per_question", "skip": 2, "questions": [21, 22, 23, 24, 25]},
    9: {"mode": "shared", "skip": 0, "questions": [26, 27, 28, 29, 30]},
}


def sort_reading_order(images):
    """Sắp xếp ảnh theo thứ tự đọc: từ trên xuống theo hàng, trái sang phải."""

    rows = []

    for img in sorted(images, key=lambda item: item["y0"]):
        if rows and abs(img["y0"] - rows[-1][0]["y0"]) <= ROW_TOLERANCE:
            rows[-1].append(img)
        else:
            rows.append([img])

    ordered = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda item: item["x0"]))

    return ordered


def make_item(page, question_number, label, img, mode):
    return {
        "source_page": page,
        "question_number": question_number,
        "option_label": label,
        "image_filename": img["filename"],
        "image_index": img["image_index"],
        "role": "question" if label is None else "option",
        "layout": mode,
        "needs_review": False,
    }


def main():
    with open(MANIFEST_FILE, "r", encoding="utf-8") as file:
        images = json.load(file)

    mapping = []

    for page, layout in PAGE_LAYOUTS.items():
        page_images = sort_reading_order(
            [img for img in images if img["page"] == page]
        )
        mode = layout["mode"]
        questions = layout["questions"]
        usable = page_images[layout["skip"]:]

        if mode == "per_question":
            expected = len(questions)
        elif mode == "per_option":
            expected = len(questions) * 3
        else:
            expected = 6

        if len(usable) != expected:
            raise ValueError(
                f"Trang {page}: cần {expected} ảnh câu hỏi "
                f"(sau khi bỏ {layout['skip']} ảnh ví dụ), "
                f"nhưng có {len(usable)}"
            )

        if mode == "per_question":
            for question_number, img in zip(questions, usable):
                mapping.append(make_item(page, question_number, None, img, mode))

        elif mode == "per_option":
            for i, question_number in enumerate(questions):
                for j, label in enumerate("ABC"):
                    img = usable[i * 3 + j]
                    mapping.append(make_item(page, question_number, label, img, mode))

        else:  # shared
            for question_number in questions:
                for label, img in zip("ABCDEF", usable):
                    mapping.append(make_item(page, question_number, label, img, mode))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(mapping, file, ensure_ascii=False, indent=4)

    print("=== KẾT QUẢ GHÉP ẢNH ===")
    for question_number in sorted({m["question_number"] for m in mapping}):
        items = [m for m in mapping if m["question_number"] == question_number]
        detail = ", ".join(
            f"{m['option_label'] or 'Q'}={m['image_filename']}" for m in items
        )
        print(f"Câu {question_number:>2}: {detail}")

    print("Tổng số dòng ghép:", len(mapping))
    print("Đã lưu:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
