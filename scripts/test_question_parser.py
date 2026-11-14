import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.question_parser import parse_hsk_file

INPUT_FILE = PROJECT_ROOT / "outputs" / "HSK1_extracted.txt"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "HSK1_questions_final.json"


def main():
    questions = parse_hsk_file(INPUT_FILE)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(questions, file, ensure_ascii=False, indent=4)

    print("Tổng số câu:", len(questions))
    print("Nghe:", sum(q["section"] == "listening" for q in questions))
    print("Đọc:", sum(q["section"] == "reading" for q in questions))
    print()

    for q in questions:
        option_images = sum(1 for o in q["options"].values() if o["image"])
        flag = "⚠" if q["needs_review"] else "✓"
        print(
            f"{flag} Câu {q['question_number']:>2} [{q['question_type']}] "
            f"ảnh câu: {'có' if q['question_image'] else '-'}, "
            f"đáp án: {len(q['options'])} ({option_images} ảnh) | "
            f"{q['question_text'][:20]}"
        )
        for note in q["review_notes"]:
            print("      -", note)

    print("\nĐã tạo file:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
