
import sys
from pathlib import Path

import fitz

# Xác định thư mục gốc của dự án
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.storage import storage


def extract_pdf_images():
    # Đường dẫn file PDF HSK1 trên Supabase Storage
    storage_path = (
        "exams/2/exam_document/"
        "1fdb079e56be454a8164b9a7cda27ec4_H10000.pdf"
    )

    print("Đang tải PDF từ Supabase Storage...")

    pdf_bytes = storage.download(storage_path)

    # Mở PDF bằng PyMuPDF
    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    # Tạo thư mục lưu hình ảnh
    output_dir = PROJECT_ROOT / "outputs" / "pdf_images"
    output_dir.mkdir(parents=True, exist_ok=True)

    total_images = 0

    # Kiểm tra các trang PDF số 3, 4, 5
    # (chỉ số trang trong Python bắt đầu từ 0)
    pages_to_extract = [2, 3, 4]

    for page_index in pages_to_extract:

        if page_index >= len(document):
            continue

        page = document[page_index]
        page_number = page_index + 1

        print(f"\nĐang kiểm tra trang PDF {page_number}...")

        images = page.get_images(full=True)

        print("Số hình ảnh tìm thấy:", len(images))

        for image_index, image_info in enumerate(images, start=1):

            xref = image_info[0]

            try:
                image_data = document.extract_image(xref)

                image_bytes = image_data["image"]
                image_ext = image_data["ext"]

                filename = (
                    f"page_{page_number:02d}_"
                    f"image_{image_index:02d}.{image_ext}"
                )

                output_path = output_dir / filename

                with open(output_path, "wb") as file:
                    file.write(image_bytes)

                # Lấy vị trí hình ảnh trong trang PDF
                rectangles = page.get_image_rects(xref)

                print("Đã lưu:", filename)
                print("Vị trí:", rectangles)

                total_images += 1

            except Exception as error:
                print(
                    f"Không thể trích xuất ảnh {image_index}:",
                    error
                )

    document.close()

    print("\nHOÀN THÀNH TRÍCH XUẤT!")
    print("Tổng số ảnh:", total_images)
    print("Thư mục lưu ảnh:", output_dir)


if __name__ == "__main__":
    extract_pdf_images()
