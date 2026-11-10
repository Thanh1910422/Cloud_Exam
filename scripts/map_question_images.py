
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_FILE = PROJECT_ROOT / "outputs" / "image_manifest.json"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "question_image_mapping.json"


def main():
    with open(MANIFEST_FILE, "r", encoding="utf-8") as file:
        images = json.load(file)

    question_mapping = []

    # Trang 4: bỏ 3 ảnh ví dụ, ghép câu 6-8
    page4 = sorted(
        [img for img in images if img["page"] == 4],
        key=lambda img: (img["y0"], img["x0"])
    )

    page4_questions = page4[3:]

    for i, question_number in enumerate([6, 7, 8]):
        for j, label in enumerate(["A", "B", "C"]):
            img = page4_questions[i * 3 + j]

            question_mapping.append({
                "source_page": 4,
                "question_number": question_number,
                "option_label": label,
                "image_filename": img["filename"],
                "image_index": img["image_index"],
                "needs_review": False
            })

    # Trang 5: câu 9-10
    page5 = sorted(
        [img for img in images if img["page"] == 5],
        key=lambda img: (img["y0"], img["x0"])
    )

    for i, question_number in enumerate([9, 10]):
        for j, label in enumerate(["A", "B", "C"]):
            img = page5[i * 3 + j]

            question_mapping.append({
                "source_page": 5,
                "question_number": question_number,
                "option_label": label,
                "image_filename": img["filename"],
                "image_index": img["image_index"],
                "needs_review": False
            })

    # Trang 6: bỏ ảnh ví dụ đầu tiên, ghép 5 ảnh vào câu 11-15
    page6 = sorted(
        [img for img in images if img["page"] == 6],
        key=lambda img: (img["y0"], img["x0"])
    )

    page6_questions = page6[1:]

    for i, question_number in enumerate([11, 12, 13, 14, 15]):
        img = page6_questions[i]

        question_mapping.append({
            "source_page": 6,
            "question_number": question_number,
            "option_label": None,
            "image_filename": img["filename"],
            "image_index": img["image_index"],
            "needs_review": False
        })
        # Trang 8: bỏ 2 ảnh ví dụ, ghép 5 ảnh vào câu 21-25
    page8 = sorted(
        [img for img in images if img["page"] == 8],
        key=lambda img: (img["y0"], img["x0"])
    )

    if len(page8) != 7:
        raise ValueError(
            f"Trang 8 phải có 7 ảnh, hiện tại có {len(page8)} ảnh"
        )

    page8_questions = page8[2:]

    for i, question_number in enumerate([21, 22, 23, 24, 25]):
        img = page8_questions[i]

        question_mapping.append({
            "source_page": 8,
            "question_number": question_number,
            "option_label": None,
            "image_filename": img["filename"],
            "image_index": img["image_index"],
            "question_type": "true_false",
            "needs_review": False
        })
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            question_mapping,
            file,
            ensure_ascii=False,
            indent=4
        )

    print("=== KẾT QUẢ GHÉP ẢNH ===")

    for question_number in range(6, 16):
        count = sum(
            1 for item in question_mapping
            if item["question_number"] == question_number
        )
        print(f"Câu {question_number}: {count} ảnh")

    print("Tổng số ảnh câu hỏi:", len(question_mapping))
    print("Đã lưu:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
