
import sys
from pathlib import Path

# Xác định thư mục gốc dự án
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import kết nối Supabase Storage
from config.storage import storage

# Import chức năng đọc PDF và OCR
from services.document_parser import extract_pdf_text


def test_pdf_parser():

    # Đường dẫn file PDF trên Supabase Storage
    storage_path = (
        "exams/2/exam_document/"
        "1fdb079e56be454a8164b9a7cda27ec4_H10000.pdf"
    )

    try:
        print("=" * 70)
        print("KIỂM TRA TRÍCH XUẤT PDF VÀ OCR")
        print("=" * 70)

        # Bước 1: Tải PDF từ Supabase
        print("\n[1] Đang tải PDF từ Supabase Storage...")

        pdf_bytes = storage.download(storage_path)

        print("Tải PDF thành công!")
        print(f"Dung lượng: {len(pdf_bytes):,} bytes")

        # Bước 2: Phân tích toàn bộ PDF
        print("\n[2] Đang phân tích PDF bằng PyMuPDF và OCR...")

        pages = extract_pdf_text(pdf_bytes)

        print(f"\nTổng số trang: {len(pages)}")

        # Bước 3: Hiển thị kết quả từng trang
        for page in pages:

            print("\n" + "=" * 70)
            print(f"TRANG {page['page']}")
            print("=" * 70)

            native_text = page["native_text"]
            ocr_text = page["ocr_text"]

            print("\n--- PHƯƠNG PHÁP 1: PYMuPDF ---")
            print(f"Số ký tự: {len(native_text)}")

            if native_text:
                print(native_text[:1500])
            else:
                print("Không trích xuất được văn bản.")

            print("\n--- PHƯƠNG PHÁP 2: TESSERACT OCR ---")
            print(f"Số ký tự: {len(ocr_text)}")

            if ocr_text:
                print(ocr_text[:1500])
            else:
                print("Không nhận diện được nội dung.")

        # Bước 4: Thống kê tổng hợp
        native_pages = sum(
            1 for page in pages
            if page["native_text"].strip()
        )

        ocr_pages = sum(
            1 for page in pages
            if page["ocr_text"].strip()
        )

        print("\n" + "=" * 70)
        print("THỐNG KÊ KẾT QUẢ")
        print("=" * 70)

        print(f"Tổng số trang PDF: {len(pages)}")
        print(f"Số trang PyMuPDF trích xuất được chữ: {native_pages}")
        print(f"Số trang OCR nhận diện được chữ: {ocr_pages}")

        print("\nHOÀN THÀNH KIỂM TRA PDF VÀ OCR!")

    except Exception as error:

        print("\nKIỂM TRA THẤT BẠI!")
        print("Loại lỗi:", type(error).__name__)
        print("Chi tiết lỗi:", error)


if __name__ == "__main__":
    test_pdf_parser()
