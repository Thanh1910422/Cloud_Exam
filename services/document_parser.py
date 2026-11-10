
from io import BytesIO

import fitz
import pytesseract

from PIL import Image


# Đường dẫn Tesseract OCR trên Windows
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def extract_pdf_text(pdf_bytes):
    """
    Đọc PDF bằng hai phương pháp song song:

    1. PyMuPDF: Trích xuất văn bản trực tiếp.
    2. Tesseract OCR: Nhận diện chữ trên ảnh của từng trang.

    Lưu riêng kết quả để so sánh hai phương pháp.
    """

    results = []

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    try:
        for page_number, page in enumerate(document, start=1):

            print(f"Đang xử lý trang {page_number}/{len(document)}...")

            # PHƯƠNG PHÁP 1: PYMuPDF
            native_text = page.get_text("text").strip()

            # PHƯƠNG PHÁP 2: TESSERACT OCR
            pix = page.get_pixmap(
                matrix=fitz.Matrix(3, 3),
                alpha=False
            )

            image = Image.open(
                BytesIO(pix.tobytes("png"))
            )

            ocr_text = pytesseract.image_to_string(
                image,
                lang="chi_sim+eng",
                config="--psm 3"
            ).strip()

            # Lưu kết quả của cả hai phương pháp
            results.append({
                "page": page_number,
                "native_text": native_text,
                "ocr_text": ocr_text
            })

    finally:
        document.close()

    return results
