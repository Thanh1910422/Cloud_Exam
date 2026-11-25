"""
Engine tạo đề tự động từ file PDF, dùng chung cho mọi cấp HSK.

Ý tưởng chính:
- Cấu trúc đề của mỗi cấp nằm trong data/levels/hsk<N>.json (phần nào, câu mấy, dạng gì,
  có bao nhiêu ảnh ví dụ). Đề khác cùng cấp dùng lại cấu hình này.
- ẢNH: xếp toàn bộ ảnh trong PDF theo thứ tự đọc (trang -> hàng -> trái sang phải),
  rồi "tiêu thụ" lần lượt cho từng phần theo cấu hình. Không cần biết phần nào ở trang nào.
- CHỮ: ưu tiên lớp chữ có sẵn trong PDF (chính xác), chỉ dùng OCR khi trang không có chữ.
- Mọi chỗ không chắc chắn đều được đánh dấu needs_review để giáo viên sửa trên app.
"""

import io
import json
import re
from decimal import Decimal
from pathlib import Path

from services.answer_key import parse_answer_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEVELS_DIR = PROJECT_ROOT / "data" / "levels"

ROW_TOLERANCE = 30          # ảnh lệch nhau < 30pt theo chiều dọc = cùng hàng
MIN_IMAGE_SIDE = 25         # bỏ qua ảnh nhỏ hơn 25pt (logo, icon trang trí)
MIN_TEXT_FOR_NATIVE = 15    # trang có < 15 ký tự chữ -> coi là trang scan, dùng OCR

TRUE_FALSE_OPTIONS = {"A": "对 (✓ Đúng)", "B": "错 (✗ Sai)"}

CJK = re.compile(r"[一-鿿]")
CJK_RUN = re.compile(r"^[一-鿿（）()，。？！、…“”：:\s]+")
QUESTION_LINE = re.compile(r"^(\d{1,3})(?:\s*[.)、．]\s*(.*)|\s*)$")
GROUP_LINE = re.compile(r"^(\d{1,3})\s*[-–—~]\s*(\d{1,3})\s*[.．、]\s*(.*)$")
LATIN_ONLY = re.compile(
    r"^[A-Za-zÀ-ỹāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü\s,.?!'’，．。？！：:“”\-]+$"
)
BANK_ITEM = re.compile(r"(?:^|\s)([A-F])\s+(?=[一-鿿])")


class BuildError(Exception):
    """Lỗi có thông báo rõ ràng cho người dùng."""


# ==========================================
# 1. CẤU HÌNH
# ==========================================
def load_level_config(level_number):
    path = LEVELS_DIR / f"hsk{level_number}.json"
    if not path.exists():
        raise BuildError(
            f"Chưa có cấu hình cho HSK{level_number}: cần tạo file {path.name} "
            f"trong data/levels (xem hsk1.json làm mẫu)."
        )
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def section_points(level_cfg, questions):
    """
    Gán điểm từng câu. Cấu hình dùng "points" (tổng điểm cả phần, vd 100) hoặc
    "points_per_question". Với "points": chia đều, câu cuối nhận phần dư để tổng đúng tròn.
    """
    for section, cfg in level_cfg["sections"].items():
        items = [q for q in questions if q["section"] == section]
        if not items:
            continue
        if "points" in cfg:
            total = Decimal(str(cfg["points"]))
            each = (total / len(items)).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
            for q in items:
                q["points"] = float(each)
            items[-1]["points"] = float(total - each * (len(items) - 1))
        else:
            for q in items:
                q["points"] = cfg["points_per_question"]


def images_needed(part):
    count = part["to"] - part["from"] + 1
    kind = part["kind"]
    if kind in ("image_true_false", "picture_sentence"):
        return count
    if kind == "image_abc":
        return count * 3
    if kind == "shared_images":
        return len(part["labels"])
    return 0


# ==========================================
# 2. ĐỌC PDF
# ==========================================
def read_pdf(pdf_bytes, ocr="auto"):
    """
    Trả về (pages, images):
      pages : [{"page": 3, "text": "...", "source": "native" | "ocr"}]
      images: [{"page", "filename", "ext", "data", "x0", "y0", "x1", "y1"}]
    """
    try:
        import pymupdf as fitz      # PyMuPDF bản mới
    except ImportError:
        import fitz                 # PyMuPDF bản cũ

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages, images = [], []

    try:
        for page_index, page in enumerate(document):
            number = page_index + 1

            # ---- chữ ----
            text = page.get_text("text", sort=True)
            source = "native"
            # Trang scan thì gần như không có lớp chữ -> mới cần OCR.
            # Trang chỉ có tranh + số câu (vd "6．7．") vẫn dùng chữ có sẵn.
            if ocr == "always" or (
                ocr == "auto" and len(re.sub(r"\s", "", text)) < MIN_TEXT_FOR_NATIVE
            ):
                ocr_text = ocr_page(page)
                if ocr_text is not None:
                    text, source = ocr_text, "ocr"
            pages.append({"page": number, "text": text, "source": source})

            # ---- ảnh ----
            for image_index, info in enumerate(page.get_images(full=True), start=1):
                xref = info[0]
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                rect = rects[0]
                # Mảnh rất nhỏ thì bỏ ngay; ảnh nhỏ khác lọc sau khi ghép mảnh
                if min(rect.width, rect.height) < 5:
                    continue

                data = document.extract_image(xref)
                images.append({
                    "page": number,
                    "filename": f"page_{number:02d}_image_{image_index:02d}.{data['ext']}",
                    "ext": data["ext"],
                    "data": data["image"],
                    "x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1,
                })
    finally:
        document.close()

    images = [
        im for im in merge_split_images(images)
        if min(im["x1"] - im["x0"], im["y1"] - im["y0"]) >= MIN_IMAGE_SIDE
    ]
    return pages, images


# ------------------------------------------
# Ghép tranh bị cắt thành nhiều mảnh
# ------------------------------------------
# Một số PDF (vd HSK2 H21006) lưu mỗi tranh thành 2 mảnh trên/dưới nằm sát nhau.
# Ghép lại để 1 tranh = 1 ảnh, nếu không số ảnh sẽ bị dư gấp đôi.
SPLIT_GAP = 2.5        # khe hở tối đa giữa 2 mảnh (pt)
SPLIT_EDGE = 3         # lệch mép trái/phải tối đa (pt)


def _is_continuation(top, bottom):
    return (
        top["page"] == bottom["page"]
        and abs(top["x0"] - bottom["x0"]) <= SPLIT_EDGE
        and abs(top["x1"] - bottom["x1"]) <= SPLIT_EDGE
        and abs(bottom["y0"] - top["y1"]) <= SPLIT_GAP
    )


def _stitch_vertical(pieces):
    """Ghép ảnh theo chiều dọc. Trả về bytes PNG, hoặc None nếu không ghép được."""
    try:
        from PIL import Image
        opened = [Image.open(io.BytesIO(p["data"])).convert("RGB") for p in pieces]
        width = max(im.width for im in opened)
        canvas = Image.new("RGB", (width, sum(im.height for im in opened)), "white")
        y = 0
        for im in opened:
            canvas.paste(im, (0, y))
            y += im.height
        out = io.BytesIO()
        canvas.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        pass

    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        pixmaps = []
        for p in pieces:
            pix = fitz.Pixmap(p["data"])
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            if pix.colorspace is None or pix.colorspace.n != 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pixmaps.append(pix)
        width = max(p.width for p in pixmaps)
        height = sum(p.height for p in pixmaps)
        canvas = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
        canvas.clear_with(255)
        y = 0
        for pix in pixmaps:
            pix.set_origin(0, y)
            canvas.copy(pix, pix.irect)
            y += pix.height
        return canvas.tobytes("png")
    except Exception:
        return None


def merge_split_images(images):
    """Gộp các mảnh ảnh nằm chồng nối tiếp nhau (cùng cột, mảnh dưới bắt đầu đúng chỗ mảnh trên kết thúc)."""
    if not images:
        return images

    remaining = sorted(images, key=lambda im: (im["page"], im["y0"], im["x0"]))
    used = set()
    result = []
    for i, first in enumerate(remaining):
        if i in used:
            continue
        group = [first]
        used.add(i)
        current = first
        for j in range(i + 1, len(remaining)):
            if j in used:
                continue
            candidate = remaining[j]
            if candidate["page"] != first["page"]:
                break
            if _is_continuation(current, candidate):
                group.append(candidate)
                used.add(j)
                current = candidate

        if len(group) == 1 or not all(p.get("data") for p in group):
            result.extend(group)
            continue

        data = _stitch_vertical(group)
        if data is None:
            result.extend(group)
            continue
        stem = first["filename"].rsplit(".", 1)[0]
        result.append({
            **first,
            "filename": f"{stem}_ghep.png",
            "ext": "png",
            "data": data,
            "x0": min(p["x0"] for p in group),
            "y0": first["y0"],
            "x1": max(p["x1"] for p in group),
            "y1": group[-1]["y1"],
        })

    # giữ thứ tự gốc theo trang để các bước sau sắp xếp lại
    return sorted(result, key=lambda im: (im["page"], im["y0"], im["x0"]))


def ocr_page(page):
    """OCR một trang. Trả về None nếu máy chưa cài Tesseract."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        import pytesseract
        from PIL import Image
        from services import document_parser  # noqa: F401 (đặt đường dẫn tesseract.exe)
    except Exception:
        return None

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(image, lang="chi_sim+eng", config="--psm 6")
    except Exception:
        return None


# ==========================================
# 3. GHÉP ẢNH
# ==========================================
START_MARKER = re.compile(r"第\s*[一1]\s*部\s*分|第\s*1\s*[-–—~至]\s*\d+\s*题")


TAIL_MARKER = re.compile(r"听力材料|卷\s*答\s*案|^\s*答\s*案\s*$", re.M)
ANSWER_MARKER = re.compile(r"卷\s*答\s*案|^\s*答\s*案\s*$", re.M)


def pages_to_ignore(level_cfg, pages):
    """
    Bỏ qua: các trang trước trang có '第一部分' (bìa, logo), và từ trang
    '听力材料' (lời thoại phần Nghe) / '答案' (đáp án) trở về sau, + ignore_pages.
    """
    ignore = set(level_cfg.get("ignore_pages", []))
    start = next((p["page"] for p in pages if START_MARKER.search(p["text"])), None)
    if start:
        ignore |= {p["page"] for p in pages if p["page"] < start}
        tail = next((p["page"] for p in pages
                     if p["page"] > start and TAIL_MARKER.search(p["text"])), None)
        if tail:
            ignore |= {p["page"] for p in pages if p["page"] >= tail}
    return ignore


def embedded_answer_text(pages):
    """Chữ của các trang đáp án nằm ngay trong file đề (vd 'H41002 卷答案'), nếu có."""
    start = next((i for i, p in enumerate(pages) if ANSWER_MARKER.search(p["text"])), None)
    if start is None:
        return ""
    text = pages[start]["text"]
    text = text[ANSWER_MARKER.search(text).start():]
    return "\n".join([text] + [p["text"] for p in pages[start + 1:]])


def order_images(images, ignore_pages=()):
    """Thứ tự đọc: theo trang, trong trang gom thành hàng rồi trái -> phải."""
    ordered = []
    for page in sorted({img["page"] for img in images}):
        if page in ignore_pages:
            continue
        rows = []
        for img in sorted((i for i in images if i["page"] == page), key=lambda i: i["y0"]):
            if rows and abs(img["y0"] - rows[-1][0]["y0"]) <= ROW_TOLERANCE:
                rows[-1].append(img)
            else:
                rows.append([img])
        for row in rows:
            ordered.extend(sorted(row, key=lambda i: i["x0"]))
    return ordered


def plan_examples(parts, ordered):
    """
    Số ảnh ví dụ ở đầu mỗi phần có thể khác nhau giữa các đề (vd đề này 1 ví dụ, đề kia 2).
    Thử các cách chia gần với cấu hình, giữ cách nào:
      1) dùng đúng tổng số ảnh của PDF,
      2) có nhiều phần bắt đầu ở ĐẦU TRANG nhất (đề HSK luôn như vậy),
      3) lệch ít nhất so với cấu hình.
    Trả về danh sách số ảnh ví dụ cho từng phần, hoặc None nếu không cách nào khớp.
    """
    from itertools import product

    image_parts = [i for i, p in enumerate(parts) if images_needed(p) > 0]
    default = [p.get("example_images", 0) for p in parts]
    first_on_page = set()
    for i, img in enumerate(ordered):
        if i == 0 or ordered[i - 1]["page"] != img["page"]:
            first_on_page.add(i)

    choices = [range(0, max(default[i], 1) + 2) for i in image_parts]
    best, best_score = None, None
    for combo in product(*choices):
        examples = list(default)
        for i, value in zip(image_parts, combo):
            examples[i] = value
        if sum(examples[i] + images_needed(parts[i]) for i in range(len(parts))) != len(ordered):
            continue
        cursor, aligned = 0, 0
        for i in image_parts:
            if cursor in first_on_page:
                aligned += 1
            cursor += examples[i] + images_needed(parts[i])
        changed = sum(abs(examples[i] - default[i]) for i in image_parts)
        score = (aligned, -changed)
        if best_score is None or score > best_score:
            best, best_score = examples, score
    return best


def assign_images(parts, ordered, notes=None):
    """
    Lần lượt lấy ảnh cho từng phần. Trả về {số câu: {"question": img | None, "options": {nhãn: img}}}.
    Số ảnh ví dụ được tự điều chỉnh nếu đề khác cấu hình; báo lỗi rõ ràng nếu không thể khớp.
    """
    examples = [p.get("example_images", 0) for p in parts]
    expected = sum(examples[i] + images_needed(p) for i, p in enumerate(parts))

    if expected != len(ordered):
        adjusted = plan_examples(parts, ordered)
        if adjusted is None:
            per_page = {}
            for img in ordered:
                per_page[img["page"]] = per_page.get(img["page"], 0) + 1
            raise BuildError(
                f"Số ảnh không khớp: cấu hình cần {expected} ảnh (gồm ảnh ví dụ) "
                f"nhưng PDF có {len(ordered)} ảnh. Ảnh theo trang: {per_page}. "
                f"Hãy kiểm tra example_images / ignore_pages trong file cấu hình cấp độ."
            )
        for part, old, new in zip(parts, examples, adjusted):
            if old != new and notes is not None:
                notes.append(
                    f"Câu {part['from']}-{part['to']}: đề này có {new} ảnh ví dụ "
                    f"(cấu hình mặc định {old}) — đã tự điều chỉnh, nên kiểm tra lại tranh."
                )
        examples = adjusted

    result = {}
    cursor = 0
    for part, example_count in zip(parts, examples):
        cursor += example_count
        numbers = range(part["from"], part["to"] + 1)
        kind = part["kind"]

        if kind in ("image_true_false", "picture_sentence"):
            for n in numbers:
                result[n] = {"question": ordered[cursor], "options": {}}
                cursor += 1
        elif kind == "image_abc":
            for n in numbers:
                result[n] = {"question": None, "options": dict(zip("ABC", ordered[cursor:cursor + 3]))}
                cursor += 3
        elif kind == "shared_images":
            labels = part["labels"]
            shared = dict(zip(labels, ordered[cursor:cursor + len(labels)]))
            for n in numbers:
                result[n] = {"question": None, "options": shared}
            cursor += len(labels)

    return result


# ==========================================
# 4. TÁCH CHỮ
# ==========================================
def document_lines(pages, ignore_pages=()):
    lines = []
    for page in pages:
        if page["page"] in ignore_pages:
            continue
        for raw in page["text"].splitlines():
            for piece in re.split(r"\s{2,}(?=\d{1,3}\s*[．.]\s)", raw.strip()):
                line = piece.strip()
                if line:
                    lines.append((page["page"], line))
    return lines


BLOCK_STOP = re.compile(r"^(第.*(部分|题)|例如|[一二三四]、)")


def block_after(lines, index, same_page=True):
    """Mọi dòng chữ Hán sau dòng index cho tới câu / nhóm / phần tiếp theo."""
    page = lines[index][0]
    collected = []
    for next_page, line in lines[index + 1:]:
        if same_page and next_page != page:
            break
        if QUESTION_LINE.match(line) or GROUP_LINE.match(line) or BLOCK_STOP.match(line):
            break
        if LATIN_ONLY.match(line) or not CJK.search(line):
            continue
        collected.append(line)
    return collected


STOP_LINE = re.compile(r"^(第.*(部分|题)|例如|[A-F]\s+[\u4e00-\u9fff])")


def continuation(lines, index):
    """Các dòng chữ Hán ngay sau dòng câu hỏi, cùng trang, trước câu/phần tiếp theo."""
    page = lines[index][0]
    collected = []
    for next_page, line in lines[index + 1:]:
        if next_page != page or QUESTION_LINE.match(line) or GROUP_LINE.match(line):
            break
        if re.match(r"^A\s", line) and re.search(r"\sB\s", line):
            # dòng "A ...  B ...  C ..." ngay sau đoạn văn là đáp án của chính câu này
            # (kể cả đáp án chỉ có số, vd "A 16   B 17   C 18   D 19")
            collected.append(line)
            break
        if STOP_LINE.match(line):
            break
        if LATIN_ONLY.match(line) or not CJK.search(line):
            continue                      # bỏ pinyin, số trang
        collected.append(line)
    return collected


def find_question_lines(lines, first, last):
    """Tìm dòng bắt đầu bằng số câu; tìm tuần tự để tránh nhầm với số trang."""
    found = {}
    cursor = 0
    for number in range(first, last + 1):
        for index in range(cursor, len(lines)):
            page, line = lines[index]
            match = QUESTION_LINE.match(line)
            if match and int(match.group(1)) == number:
                previous = ""
                for back in range(index - 1, max(index - 4, -1), -1):
                    candidate = lines[back][1]
                    if re.fullmatch(r"[（()）\s]*", candidate):
                        continue           # dòng chỉ có "（" do PDF tách
                    previous = candidate
                    break
                found[number] = {
                    "page": page,
                    "index": index,
                    "text": (match.group(2) or "").strip(),
                    "more": continuation(lines, index),
                    "block": block_after(lines, index),
                    "pinyin": previous if LATIN_ONLY.match(previous) else "",
                    "raw_text": line,
                }
                cursor = index + 1
                break
    return found


def find_group_blocks(lines):
    """{80: {"to": 81, "page": 12, "block": [...]}} cho các dòng '80-81．'."""
    groups = {}
    for index, (page, line) in enumerate(lines):
        match = GROUP_LINE.match(line)
        if match:
            first, last = int(match.group(1)), int(match.group(2))
            block = ([match.group(3)] if match.group(3).strip() else []) + \
                block_after(lines, index, same_page=False)
            groups.setdefault(first, {"to": last, "page": page, "block": block})
    return groups


def split_passage_group(block, count, labels):
    """Đoạn văn + nhiều câu ★ (mỗi câu có dòng đáp án) -> [(câu hỏi, {đáp án})]."""
    passage, items, current = [], [], None
    for line in block:
        if line.lstrip().startswith("★"):
            current = {"question": line, "options": {}}
            items.append(current)
        elif current is not None and re.match(r"^A\s", line) and not current["options"]:
            current["options"] = parse_inline_options(line, labels)
        elif current is None:
            passage.append(line)
    text = "".join(clean_chinese(x) for x in passage)
    return text, items[:count]


CJK_PUNCT = "\u4e00-\u9fff，。？！、：；（）“”《》「」『』‘’…—"


def clean_chinese(text):
    """Bỏ rác OCR ở đầu và khoảng trắng chen giữa các chữ Hán: '- 做 饭 ' -> '做饭'."""
    text = re.sub(rf"^[^{CJK_PUNCT}A-Za-z0-9★]+", "", text.strip())
    text = re.sub(rf"(?<=[{CJK_PUNCT}])\s+(?=[{CJK_PUNCT}])", "", text)
    text = re.sub(r"[（(]\s*[）)]", "（　　）", text)       # chỗ trống điền từ
    text = re.sub(r"★\s*", "★ ", text)
    return text.strip()


def parse_inline_options(text, labels="ABC"):
    """'A 星期二   星期三   C 星期五' -> {A, B, C}; nhãn có thể bị OCR làm mất."""
    text = text.strip()
    # Cách 1: đủ các nhãn A, B, C(, D) theo đúng thứ tự trong dòng
    positions, start = [], 0
    for label in labels:
        m = re.compile(rf"(?:^|\s){label}\s+").search(text, start)
        if not m:
            positions = []
            break
        positions.append((label, m.start(), m.end()))
        start = m.end()
    if positions and positions[0][1] == 0:
        result = {}
        for i, (label, _, end) in enumerate(positions):
            stop = positions[i + 1][1] if i + 1 < len(positions) else len(text)
            result[label] = clean_chinese(re.sub(r"\s*[√✓]\s*$", "", text[end:stop]))
        if all(result.values()):
            return result
    # Cách 2: các đáp án cách nhau >= 2 dấu cách (OCR có thể làm mất nhãn)
    text = re.sub(r"(^|\s)([A-F])\s+", r"\1\2 ", text)
    chunks = [c.strip() for c in re.split(r"\s{2,}", text) if c.strip()]
    if len(chunks) != len(labels):
        return {}
    return {label: clean_chinese(re.sub(r"^[A-F]\s+", "", chunk)) for label, chunk in zip(labels, chunks)}


def find_word_bank(lines, pages_of_part, labels):
    """Tìm các dòng 'A 火车站   B 对不起' trong các trang của phần thi."""
    bank = {}
    for page, line in lines:
        if page not in pages_of_part:
            continue
        matches = list(BANK_ITEM.finditer(line))
        for i, m in enumerate(matches):
            label = m.group(1)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            chunk = CJK_RUN.match(line[m.end():end].strip())
            if label in labels and label not in bank and chunk:
                bank[label] = clean_chinese(chunk.group(0))
    return bank


# ==========================================
# 5. DỰNG CÂU HỎI
# ==========================================
def build_questions(level_cfg, pages, images, fixes=None, answers=None, text_answers=None):
    parts = level_cfg["parts"]
    ignore = pages_to_ignore(level_cfg, pages)

    image_notes = []
    image_map = assign_images(parts, order_images(images, ignore), image_notes)

    lines = document_lines(pages, ignore)
    first = min(p["from"] for p in parts)
    last = max(p["to"] for p in parts)
    found = find_question_lines(lines, first, last)
    groups = find_group_blocks(lines)

    questions = {}
    skipped = []

    for part in parts:
        numbers_in_part = range(part["from"], part["to"] + 1)
        in_group = any(part["from"] <= g <= part["to"] for g in groups)
        if images_needed(part) == 0 and not in_group and not any(n in found for n in numbers_in_part):
            skipped.append(f"{part['from']}-{part['to']}")
            continue

        kind = part["kind"]
        section = part["section"]
        numbers = list(range(part["from"], part["to"] + 1))

        if kind in WRITING_KINDS:
            for n in numbers:
                questions[n] = build_writing_question(n, part, found.get(n, {}), level_cfg)
            continue

        if kind == "sort_sentences":
            for n in numbers:
                questions[n] = build_sort_question(n, part, found.get(n, {}), level_cfg)
            continue

        if kind == "picture_sentence":
            for n in numbers:
                img = image_map.get(n, {}).get("question")
                questions[n] = build_picture_question(n, part, found.get(n, {}), img, level_cfg)
            continue

        if kind == "passage_group":
            labels = part.get("labels", "ABCD")
            for first, group in groups.items():
                if not (part["from"] <= first <= part["to"]):
                    continue
                count = group["to"] - first + 1
                passage, items = split_passage_group(group["block"], count, labels)
                for offset in range(count):
                    n = first + offset
                    notes = []
                    item = items[offset] if offset < len(items) else {"question": "", "options": {}}
                    if not item["options"]:
                        notes.append(f"Không tách được đáp án {'/'.join(labels)}")
                    questions[n] = {
                        "level": level_cfg["level"], "section": section,
                        "question_number": n, "question_type": "multiple_choice",
                        "question_text": (passage + "\n" + clean_chinese(item["question"])).strip(),
                        "pinyin": "", "question_image": None,
                        "options": {l: {"text": item["options"].get(l, ""), "image": None} for l in labels},
                        "correct_answer": None, "points": 0,
                        "raw_text": "", "source_page": group["page"], "review_notes": notes,
                    }
            for n in numbers:
                if n not in questions:
                    questions[n] = {
                        "level": level_cfg["level"], "section": section,
                        "question_number": n, "question_type": "multiple_choice",
                        "question_text": "", "pinyin": "", "question_image": None,
                        "options": {l: {"text": "", "image": None} for l in labels},
                        "correct_answer": None, "points": 0, "raw_text": "",
                        "source_page": None, "review_notes": ["Không tìm thấy nhóm câu trong PDF"],
                    }
            continue
        part_pages = {found[n]["page"] for n in numbers if n in found}

        bank = {}
        if kind == "shared_text":
            bank = find_word_bank(lines, part_pages, part["labels"])

        for n in numbers:
            info = found.get(n, {})
            imgs = image_map.get(n, {"question": None, "options": {}})
            notes = []

            if kind in ("image_true_false", "text_true_false"):
                labels = "AB"
            elif kind in ("image_abc", "text_abc"):
                labels = "ABC"
            elif kind == "text_abcd":
                labels = "ABCD"
            else:
                labels = part["labels"]

            options = {
                label: {
                    "text": TRUE_FALSE_OPTIONS.get(label, "") if labels == "AB" else "",
                    "image": None,
                }
                for label in labels
            }
            for label, img in imgs["options"].items():
                options[label]["image"] = img["filename"]

            question_text = ""
            if kind in ("text_abc", "text_abcd"):
                parsed = parse_inline_options(info.get("text", ""), labels)
                if not parsed:
                    # "★ 他今天：   A 很忙   B 很累   C 很高兴" -> câu hỏi + đáp án cùng dòng
                    split = re.search(r"(^|\s{2,})A\s", info.get("text", ""))
                    if split and split.start() > 0:
                        parsed = parse_inline_options(info["text"][split.start():], labels)
                        if parsed:
                            info = dict(info, text=info["text"][:split.start()])
                if not parsed:
                    # tìm dòng đáp án "A ...  B ...  C ..." trong các dòng tiếp theo
                    more = info.get("more", [])
                    for i, line in enumerate(more):
                        if re.match(r"^A\s", line):
                            parsed = parse_inline_options(line, labels)
                            if parsed:
                                info = dict(info, text="\n".join([info.get("text", "")] + more[:i]),
                                            more=[])
                            break
                for label, text in parsed.items():
                    options[label]["text"] = text
                if not parsed:
                    notes.append(f"Không tách được đáp án {'/'.join(labels)}")
            elif kind == "shared_text":
                for label, text in bank.items():
                    options[label]["text"] = text
                if len(bank) < len(labels):
                    missing = "".join(l for l in labels if l not in bank)
                    notes.append(f"Thiếu nội dung đáp án {missing}")

            if part.get("text"):
                text_lines = [info.get("text", "")] + info.get("more", [])
                question_text = "\n".join(
                    t for t in (clean_chinese(x) for x in text_lines) if t
                )
                # dòng tiếp nối của cùng một câu (không phải ★ / lời thoại mới) -> nối liền
                question_text = re.sub(r"\n(?![★男女问]|[A-F][：:])", "", question_text)
                # "（　　）" ở cuối câu là ô ghi đáp án, không phải chỗ trống trong câu
                question_text = re.sub(r"\s*（　　）$", "", question_text)
                if not CJK.search(question_text):
                    question_text = ""
                    notes.append("Không đọc được chữ Hán của câu hỏi")

            if part.get("text") or kind in ("text_abc", "text_abcd"):
                if not info:
                    notes.append("Không tìm thấy dòng câu hỏi trong PDF")

            questions[n] = {
                "level": level_cfg["level"],
                "section": section,
                "question_number": n,
                "question_type": "multiple_choice",
                "question_text": question_text,
                "pinyin": info.get("pinyin", ""),
                "question_image": imgs["question"]["filename"] if imgs["question"] else None,
                "options": options,
                "correct_answer": None,
                "points": 0,
                "raw_text": info.get("raw_text", ""),
                "source_page": info.get("page"),
                "review_notes": notes,
            }

    if skipped:
        print(f"Bỏ qua phần không có trong PDF: câu {', '.join(skipped)}")

    for note in image_notes:
        print(note)
        first = int(re.match(r"Câu (\d+)", note).group(1))
        if first in questions:
            questions[first]["review_notes"].append(note)

    apply_fixes(questions, fixes or {})
    apply_answers(questions, answers or {})

    for number, text in (text_answers or {}).items():
        q = questions.get(number)
        if q and q["question_type"] in ("fill_blank", "essay"):
            q["options"]["A"]["text"] = text
            q["correct_answer"] = "A"

    section_points(level_cfg, [questions[n] for n in sorted(questions)])

    for q in questions.values():
        if q["correct_answer"] is None:
            q["review_notes"].append("Chưa có đáp án đúng")
        q["needs_review"] = bool(q["review_notes"]) and not q.pop("verified", False)

    return [questions[n] for n in sorted(questions)]


def apply_fixes(questions, fixes):
    for key, fix in fixes.items():
        if key.startswith("_") or not key.isdigit() or int(key) not in questions:
            continue
        q = questions[int(key)]
        for field in ("question_text", "pinyin", "correct_answer"):
            if field in fix:
                q[field] = fix[field]
        for label, text in fix.get("options", {}).items():
            q["options"].setdefault(label, {"text": "", "image": None})["text"] = text
        if "answer_text" in fix and q["question_type"] == "fill_blank":
            q["options"]["A"]["text"] = fix["answer_text"]
            q["correct_answer"] = "A"
        if "question_text" in fix:
            q["review_notes"] = [n for n in q["review_notes"] if "câu hỏi" not in n]
        if fix.get("verified"):
            q["verified"] = True


def apply_answers(questions, answers):
    for number, label in answers.items():
        q = questions.get(number)
        if q and q["question_type"] == "multiple_choice" and label in q["options"]:
            q["correct_answer"] = label


def answers_from_text(text):
    return parse_answer_key(text)


TEXT_ANSWER = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*([\u4e00-\u9fff].*)$")
SORT_ANSWER = re.compile(r"(?<!\d)(\d{1,3})\s*[.．、]\s*([A-F]{3,6})(?![A-Za-z])")


def text_answers_from_text(text):
    """
    Đáp án dạng chữ: {71: "弟弟高兴地笑了。", 76: "出", 56: "ACB"}.
    Đáp án bị xuống dòng (vd câu 91) được nối lại.
    """
    answers = {n: a for n, a in ((int(n), a) for n, a in SORT_ANSWER.findall(text or ""))}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        match = TEXT_ANSWER.match(line)
        if match:
            current = int(match.group(1))
            answers[current] = match.group(2)
        elif current and line and CJK.search(line) and not re.match(r"^(第|（|\(|[一二三四]、)", line) \
                and not re.match(r"^\d", line):
            answers[current] += line          # phần tiếp của đáp án dài
        else:
            current = None
    return {n: clean_chinese(a) if not re.fullmatch(r"[A-F]+", a) else a for n, a in answers.items()}


WRITING_KINDS = ("arrange_words", "write_char")


def build_sort_question(n, part, info, level_cfg):
    """Sắp xếp 3 câu A/B/C: học viên gõ thứ tự (vd BAC), máy chấm theo đáp án."""
    lines = [info.get("text", "")] + info.get("block", [])
    sentences = {}
    for line in lines:
        m = re.match(r"^([A-F])\s+(.+)$", line.strip())
        if m and m.group(1) not in sentences:
            sentences[m.group(1)] = clean_chinese(m.group(2))
    notes = [] if len(sentences) >= 3 else ["Không đọc đủ 3 câu A/B/C"]
    text = "\n".join(f"{k} {v}" for k, v in sorted(sentences.items()))
    return {
        "level": level_cfg["level"], "section": part["section"],
        "question_number": n, "question_type": "fill_blank",
        "question_text": text + "\n（Gõ thứ tự đúng của các câu, ví dụ: BAC）",
        "pinyin": "", "question_image": None,
        "options": {"A": {"text": "", "image": None}},
        "correct_answer": None, "points": 0,
        "raw_text": info.get("raw_text", ""), "source_page": info.get("page"),
        "review_notes": notes + ([] if info else ["Không tìm thấy dòng câu hỏi trong PDF"]),
    }


def build_picture_question(n, part, info, img, level_cfg):
    """Nhìn tranh, dùng từ cho sẵn đặt câu: bài tự luận, giáo viên chấm."""
    word = clean_chinese(info.get("text", ""))
    notes = [] if word else ["Không đọc được từ cho sẵn"]
    return {
        "level": level_cfg["level"], "section": part["section"],
        "question_number": n, "question_type": "essay",
        "question_text": f"看图，用词造句：{word}" if word else "看图，用词造句。",
        "pinyin": "", "question_image": img["filename"] if img else None,
        "options": {"A": {"text": "", "image": None}},
        "correct_answer": None, "points": 0,
        "raw_text": info.get("raw_text", ""), "source_page": info.get("page"),
        "review_notes": notes + ([] if img else ["Thiếu tranh"]),
    }


def build_writing_question(n, part, info, level_cfg):
    """Câu Viết: học viên gõ đáp án; đáp án đúng lưu ở đáp án A (máy so khớp để chấm)."""
    notes = []
    raw = info.get("text", "")

    if part["kind"] == "arrange_words":
        words = [w for w in re.split(r"\s+", raw.strip()) if w]
        question_text = " / ".join(words)
        if len(words) < 2:
            notes.append("Không tách được các từ cần sắp xếp")
    else:  # write_char: viết chữ Hán theo pinyin
        text = clean_chinese(raw)
        if text.startswith("）"):
            text = "（" + text                # PDF tách "（" sang dòng khác
        pinyin = info.get("pinyin", "").strip()
        if pinyin:
            text = re.sub(r"（\s*）|（　　）", f"（ {pinyin} ）", text, count=1)
        question_text = text
        if not pinyin:
            notes.append("Không đọc được pinyin gợi ý")

    if not info:
        notes.append("Không tìm thấy dòng câu hỏi trong PDF")

    return {
        "level": level_cfg["level"],
        "section": part["section"],
        "question_number": n,
        "question_type": "fill_blank",
        "question_text": question_text,
        "pinyin": info.get("pinyin", ""),
        "question_image": None,
        "options": {"A": {"text": "", "image": None}},
        "correct_answer": None,
        "points": 0,
        "raw_text": info.get("raw_text", ""),
        "source_page": info.get("page"),
        "review_notes": notes,
    }


# ==========================================
# 6. GHI DATABASE
# ==========================================
def save_to_db(cursor, exam_id, level_cfg, questions, image_url, replace=False, log=print):
    """Ghi câu hỏi vào DB. image_url(filename) -> URL lưu vào cột image_url."""
    section_ids = {}
    for order, (section_type, cfg) in enumerate(level_cfg["sections"].items(), start=1):
        cursor.execute(
            "SELECT id FROM exam_sections WHERE exam_id = %s AND section_type = %s",
            (exam_id, section_type),
        )
        row = cursor.fetchone()
        if row:
            section_ids[section_type] = row["id"]
        else:
            cursor.execute("""
                INSERT INTO exam_sections
                    (exam_id, section_type, section_title, time_limit_minutes, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (exam_id, section_type, cfg["title"], cfg["minutes"], order))
            section_ids[section_type] = cursor.fetchone()["id"]

    for section_type, section_id in section_ids.items():
        cursor.execute("SELECT COUNT(*) AS n FROM questions WHERE section_id = %s", (section_id,))
        existing = cursor.fetchone()["n"]
        if existing and not replace:
            raise BuildError(
                f"Phần {section_type} đã có {existing} câu. Chọn 'tạo lại' (--replace) để xóa và "
                f"tạo lại (LƯU Ý: mọi chỉnh sửa giáo viên đã làm trên app sẽ mất)."
            )
        if existing:
            cursor.execute("""
                SELECT COUNT(*) AS n FROM student_answers
                WHERE question_id IN (SELECT id FROM questions WHERE section_id = %s)
            """, (section_id,))
            if cursor.fetchone()["n"]:
                raise BuildError(
                    f"Phần {section_type} đã có học viên làm bài, không thể xóa để tạo lại. "
                    f"Hãy tạo một đề thi mới."
                )
            cursor.execute("DELETE FROM questions WHERE section_id = %s", (section_id,))
            log(f"Đã xóa {existing} câu cũ của phần {section_type}")

    # Ghi theo lô (1 câu SQL cho mọi câu hỏi, 1 câu cho mọi đáp án):
    # nhanh hơn rất nhiều khi database ở xa (vd web chạy trên Vercel).
    if not questions:
        return
    q_rows = [
        (
            section_ids[q["section"]],
            q.get("question_type", "multiple_choice"),
            q["question_text"] or "",
            image_url(q["question_image"]) if q["question_image"] else None,
            Decimal(str(q["points"])),
            q["question_number"],
        )
        for q in questions
    ]
    cursor.execute(
        "INSERT INTO questions (section_id, question_type, question_text, image_url, "
        "audio_url, points, sort_order) VALUES "
        + ", ".join(["(%s, %s, %s, %s, NULL, %s, %s)"] * len(q_rows))
        + " RETURNING id, section_id, sort_order",
        [value for row in q_rows for value in row],
    )
    ids = {(r["section_id"], r["sort_order"]): r["id"] for r in cursor.fetchall()}

    o_rows = []
    for q in questions:
        question_id = ids[(section_ids[q["section"]], q["question_number"])]
        for label, option in q["options"].items():
            o_rows.append((
                question_id,
                label,
                option["text"] or "",
                label == q["correct_answer"],
                image_url(option["image"]) if option["image"] else None,
            ))
    if o_rows:
        cursor.execute(
            "INSERT INTO answer_options (question_id, option_label, option_text, "
            "is_correct, option_image_url) VALUES "
            + ", ".join(["(%s, %s, %s, %s, %s)"] * len(o_rows)),
            [value for row in o_rows for value in row],
        )


def used_image_files(questions):
    names = set()
    for q in questions:
        if q["question_image"]:
            names.add(q["question_image"])
        for option in q["options"].values():
            if option["image"]:
                names.add(option["image"])
    return sorted(names)
