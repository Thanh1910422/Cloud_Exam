
import sys
import json
from pathlib import Path

# Thêm thư mục gốc Cloud_Exam vào đường dẫn Python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.question_parser import parse_hsk_file


INPUT_FILE = PROJECT_ROOT / "outputs" / "HSK1_extracted.txt"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "HSK1_questions_with_images.json"


def main():
    questions = parse_hsk_file(INPUT_FILE)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            questions,
            file,
            ensure_ascii=False,
            indent=4
        )

    print("Tổng số câu nhận diện:", len(questions))

    listening = [
        q for q in questions
        if q["section"] == "listening"
    ]

    reading = [
        q for q in questions
        if q["section"] == "reading"
    ]

    print("Số câu Nghe:", len(listening))
    print("Số câu Đọc:", len(reading))

    print("\n--- KIỂM TRA ẢNH ---")

    for question in questions:
        print(
            f"Câu {question['question_number']} "
            f"- Trang {question['source_page']} "
            f"- Số ảnh: {len(question['images'])}"
        )

    print("\nĐã tạo file:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
