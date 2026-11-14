# Sửa tay cho đề tạo tự động

Tạo file `exam_<id>.json` (ví dụ `exam_3.json`) khi muốn sửa trước những chỗ OCR đọc sai,
rồi chạy lại `python scripts/build_exam.py --exam-id <id> --replace`.

```json
{
    "24": {"question_text": "坐"},
    "31": {"options": {"A": "中国人", "B": "八点了"}},
    "36": {"question_text": "你叫什么（ ）？", "correct_answer": "D"}
}
```

Cách dễ hơn: tạo đề xong thì sửa trực tiếp trên app (nút ✏ Sửa) — không cần file này.
