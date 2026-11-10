
import re
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

IMAGE_MAPPING_FILE = (
    PROJECT_ROOT / "outputs" / "question_image_mapping.json"
)


def detect_section(page_number):
    """Xác định phần thi và khoảng số câu theo trang."""

    page_config = {
        3: ("listening", 1, 5),
        4: ("listening", 6, 8),
        5: ("listening", 9, 10),
        6: ("listening", 11, 15),
        7: ("listening", 16, 20),
        8: ("reading", 21, 25),
        9: ("reading", 26, 30),
        10: ("reading", 31, 35),
        11: ("reading", 36, 40)
    }

    return page_config.get(page_number, ("unknown", 0, 0))


def load_image_mapping():
    """Đọc danh sách ảnh đã trích xuất."""

    if not IMAGE_MAPPING_FILE.exists():
        return []

    with open(IMAGE_MAPPING_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def extract_questions(text, min_number, max_number):
    """Tách câu hỏi theo khoảng số câu."""

    questions = []
    current_question = None

    def save_current_question():
        if current_question:
            questions.append(current_question.copy())

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        match = re.match(
            r"^(\d{1,2})(?:[.)、]\s*(.*)|\s*)$",
            line
        )

        if match:
            number = int(match.group(1))

            if min_number <= number <= max_number:
                save_current_question()

                remaining_text = (match.group(2) or "").strip()

                current_question = {
                    "question_number": number,
                    "question_text": remaining_text,
                    "options": {},
                    "raw_text": line
                }

                continue

        if current_question:
            current_question["raw_text"] += "\n" + line

            option_match = re.match(
                r"^([A-F])[\s.)、:：]+(.+)$",
                line
            )

            if option_match:
                label = option_match.group(1)
                value = option_match.group(2).strip()

                current_question["options"][label] = value

            elif not current_question["question_text"]:
                current_question["question_text"] = line

    save_current_question()

    return questions


def attach_images(questions, image_mapping):
    """
    Gắn danh sách ảnh theo trang vào câu hỏi.

    Chưa tự gán số câu khi chưa xác định được vị trí
    và thứ tự câu hỏi tương ứng.
    """

    images_by_page = {}

    for image in image_mapping:
        page = image["source_page"]

        images_by_page.setdefault(page, []).append(image)

    for question in questions:
        page = question["source_page"]

        page_images = images_by_page.get(page, [])

        question["images"] = [
            {
                "filename": image["image_filename"],
                "image_index": image["image_index"]
            }
            for image in page_images
        ]

        question["needs_image_review"] = bool(page_images)

    return questions


def parse_hsk_file(input_file):
    """Đọc TXT, nhận diện câu hỏi và gắn dữ liệu ảnh."""

    content = Path(input_file).read_text(encoding="utf-8")

    pages = re.split(r"TRANG\s+(\d+)", content)

    results = []

    for i in range(1, len(pages), 2):
        page_number = int(pages[i])
        page_content = pages[i + 1]

        section, min_number, max_number = detect_section(page_number)

        if section == "unknown":
            continue

        questions = extract_questions(
            page_content,
            min_number,
            max_number
        )

        for question in questions:
            results.append({
                "level": 1,
                "section": section,
                "question_number": question["question_number"],
                "question_text": question["question_text"],
                "options": question["options"],
                "correct_answer": None,
                "raw_text": question["raw_text"],
                "source_page": page_number,
                "images": [],
                "needs_image_review": False,
                "needs_review": True
            })

    image_mapping = load_image_mapping()

    results = attach_images(results, image_mapping)

    return results
