
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.storage import storage
from services.document_parser import extract_pdf_text


def export_pdf_text():
    storage_path = (
        "exams/2/exam_document/"
        "1fdb079e56be454a8164b9a7cda27ec4_H10000.pdf"
    )

    print("Đang tải file PDF...")
    pdf_bytes = storage.download(storage_path)

    print("Đang trích xuất nội dung...")
    pages = extract_pdf_text(pdf_bytes)

    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "HSK1_extracted.txt"

    with open(output_file, "w", encoding="utf-8") as file:
        for page in pages:
            file.write(f"\n{'=' * 50}\n")
            file.write(f"TRANG {page['page']}\n")
            file.write(f"{'=' * 50}\n\n")

            native_text = page.get("native_text", "").strip()
            ocr_text = page.get("ocr_text", "").strip()

            # Ưu tiên OCR nếu nhận diện được nội dung.
            extracted_text = ocr_text if ocr_text else native_text

            file.write(extracted_text)
            file.write("\n")

    print("Hoàn thành!")
    print(f"File kết quả: {output_file}")


if __name__ == "__main__":
    export_pdf_text()
