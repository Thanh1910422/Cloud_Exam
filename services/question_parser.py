"""
Tạo dữ liệu câu hỏi HSK1 hoàn chỉnh (40 câu) từ:
  1. outputs/HSK1_extracted.txt         (text OCR)
  2. outputs/question_image_mapping.json (ảnh đã ghép theo câu / đáp án)
  3. data/hsk1_manual_fixes.json        (sửa tay chỗ OCR đọc sai)

Khác bản cũ:
- Luôn tạo đủ 40 câu theo cấu trúc đề, kể cả câu 1-8 mà OCR không đọc được số.
- Ảnh gắn theo question_number + option_label, không gắn cả trang vào mọi câu.
- Tách được đáp án A/B/C trên cùng một dòng (câu 16-20), kể cả khi OCR mất chữ "B".
- Dòng pinyin nằm TRÊN dòng chữ Hán, nên lấy dòng phía trước làm pinyin.
"""

import re
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

IMAGE_MAPPING_FILE = PROJECT_ROOT / "outputs" / "question_image_mapping.json"
MANUAL_FIXES_FILE = PROJECT_ROOT / "data" / "hsk1_manual_fixes.json"


# Cấu trúc đề HSK1: (từ câu, đến câu, phần thi, trang, part, loại câu, nhãn đáp án)
# Lưu ý: database chỉ cho question_type IN ('multiple_choice','fill_blank','essay'),
# nên câu Đúng/Sai cũng lưu là multiple_choice với 2 đáp án A=对, B=错.
HSK1_STRUCTURE = [
    (1, 5, "listening", 3, 1, "multiple_choice", "AB"),
    (6, 10, "listening", None, 2, "multiple_choice", "ABC"),
    (11, 15, "listening", 6, 3, "multiple_choice", "ABCDEF"),
    (16, 20, "listening", 7, 4, "multiple_choice", "ABC"),
    (21, 25, "reading", 8, 1, "multiple_choice", "AB"),
    (26, 30, "reading", 9, 2, "multiple_choice", "ABCDEF"),
    (31, 35, "reading", 10, 3, "multiple_choice", "ABCDEF"),
    (36, 40, "reading", 11, 4, "multiple_choice", "ABCDEF"),
]

TRUE_FALSE_OPTIONS = {"A": "对 (✓ Đúng)", "B": "错 (✗ Sai)"}

PAGE_SPLIT = re.compile(r"TRANG\s+(\d+)")
QUESTION_LINE = re.compile(r"^(\d{1,2})(?:[.)、]\s*(.*)|\s*)$")
LATIN_ONLY = re.compile(r"^[A-Za-zÀ-ỹāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü\s,.?!'’]+$")


def split_pages(content):
    parts = PAGE_SPLIT.split(content)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def parse_inline_options(text, labels="ABC"):
    """
    Tách 'A 星期二        星期三     C 星期五' thành {A:..., B:..., C:...}.
    Các đáp án cách nhau bởi >= 2 dấu cách; nhãn chữ cái có thể bị OCR làm mất.
    """

    # Gộp khoảng trắng thừa ngay sau nhãn: "A  车" -> "A 车"
    text = re.sub(r"(^|\s)([A-F])\s+", r"\1\2 ", text.strip())

    chunks = [c.strip() for c in re.split(r"\s{2,}", text) if c.strip()]

    if len(chunks) != len(labels):
        return {}

    options = {}
    for label, chunk in zip(labels, chunks):
        options[label] = re.sub(r"^[A-F]\s+", "", chunk).strip()

    return options


def extract_numbered_lines(page_text, numbers):
    """Lấy dòng có số câu + dòng pinyin ngay phía trên (nếu có)."""

    found = {}
    previous_line = ""

    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = QUESTION_LINE.match(line)
        if match and int(match.group(1)) in numbers:
            number = int(match.group(1))
            found[number] = {
                "text": (match.group(2) or "").strip(),
                "pinyin": previous_line if LATIN_ONLY.match(previous_line) else "",
                "raw_text": line,
            }

        previous_line = line

    return found


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def build_skeleton():
    questions = {}

    for start, end, section, page, part, qtype, labels in HSK1_STRUCTURE:
        for number in range(start, end + 1):
            if page is None:  # câu 6-10 nằm trên trang 4 và 5
                source_page = 4 if number <= 8 else 5
            else:
                source_page = page

            options = {}
            if labels == "AB":  # dạng Đúng / Sai
                options = {
                    label: {"text": text, "image": None}
                    for label, text in TRUE_FALSE_OPTIONS.items()
                }

            questions[number] = {
                "level": 1,
                "section": section,
                "part": part,
                "question_number": number,
                "question_type": qtype,
                "question_text": "",
                "pinyin": "",
                "question_image": None,
                "options": options,
                "option_labels": labels,
                "correct_answer": None,
                "raw_text": "",
                "source_page": source_page,
                "review_notes": [],
            }

    return questions


def apply_ocr_text(questions, pages):
    for number, q in questions.items():
        page_text = pages.get(q["source_page"], "")
        found = extract_numbered_lines(page_text, {number})
        if number not in found:
            continue

        info = found[number]
        q["raw_text"] = info["raw_text"]
        q["pinyin"] = info["pinyin"]

        # Câu 1-15 chỉ nghe + nhìn tranh, phần text OCR là rác ("[|", "A"...)
        if number <= 15:
            continue

        if q["part"] == 4 and q["section"] == "listening":
            options = parse_inline_options(info["text"], "ABC")
            for label, text in options.items():
                q["options"][label] = {"text": text, "image": None}
            if not options:
                q["review_notes"].append("Không tách được đáp án A/B/C")
        else:
            q["question_text"] = info["text"]


def apply_images(questions, mapping):
    for item in mapping:
        q = questions.get(item["question_number"])
        if not q:
            continue

        if item["option_label"] is None:
            q["question_image"] = item["image_filename"]
        else:
            option = q["options"].setdefault(
                item["option_label"], {"text": "", "image": None}
            )
            option["image"] = item["image_filename"]


def apply_manual_fixes(questions, fixes):
    for key, fix in fixes.items():
        if key.startswith("_"):
            continue

        q = questions.get(int(key))
        if not q:
            continue

        for field in ("question_text", "pinyin", "correct_answer"):
            if field in fix:
                q[field] = fix[field]

        for label, text in fix.get("options", {}).items():
            option = q["options"].setdefault(label, {"text": "", "image": None})
            option["text"] = text

        if "note" in fix:
            q["review_notes"].append(fix["note"])

        if fix.get("verified"):
            q["verified"] = True


def finalize(questions):
    for q in questions.values():
        # Câu dạng ghép A-F mà chưa có đáp án nào -> cần nhập tay
        if not any(o["text"] or o["image"] for o in q["options"].values()):
            q["review_notes"].append("Chưa có nội dung đáp án A-F, cần nhập tay")

        if q["section"] == "reading" and not q["question_text"]:
            q["review_notes"].append("Thiếu nội dung câu hỏi")

        if q["correct_answer"] is None:
            q["review_notes"].append("Chưa có đáp án đúng")

        # Luôn có đủ nhãn đáp án (vd A-F), kể cả khi OCR không đọc được chữ
        for label in q.get("option_labels", ""):
            q["options"].setdefault(label, {"text": "", "image": None})

        q["options"] = dict(sorted(q["options"].items()))
        q["needs_review"] = bool(q["review_notes"]) and not q.get("verified")
        q.pop("option_labels", None)

    return [questions[n] for n in sorted(questions)]


def parse_hsk_file(input_file):
    """Đọc TXT + ảnh + bản sửa tay, trả về danh sách 40 câu HSK1."""

    content = Path(input_file).read_text(encoding="utf-8")
    pages = split_pages(content)

    questions = build_skeleton()
    apply_ocr_text(questions, pages)
    apply_images(questions, load_json(IMAGE_MAPPING_FILE, []))
    apply_manual_fixes(questions, load_json(MANUAL_FIXES_FILE, {}))

    return finalize(questions)
