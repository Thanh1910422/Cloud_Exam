"""Đọc chuỗi đáp án dạng "1✓ 2× 6B 7.C 11、F" -> {1: "A", 2: "B", 6: "B", ...}."""

import re

# Câu Đúng/Sai được lưu với A = 对 (Đúng), B = 错 (Sai)
ANSWER_SYMBOLS = {
    "✓": "A", "√": "A", "✔": "A", "V": "A", "对": "A",
    "×": "B", "✗": "B", "✘": "B", "X": "B", "错": "B",
}

ANSWER_PATTERN = re.compile(
    r"(?<!\d)(\d{1,3})\s*[.:)、．\-]?\s*([A-Fa-f✓√✔×✗✘xXvV对错])"
)


def parse_answer_key(text):
    answers = {}
    for number, value in ANSWER_PATTERN.findall(text or ""):
        value = value.upper() if value.isascii() else value
        answers[int(number)] = ANSWER_SYMBOLS.get(value, value)
    return answers
