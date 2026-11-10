
import sys
from pathlib import Path

import fitz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.storage import storage


def create_preview():

    storage_path = (
        "exams/2/exam_document/"
        "1fdb079e56be454a8164b9a7cda27ec4_H10000.pdf"
    )

    print("Đang tải PDF...")
    pdf_bytes = storage.download(storage_path)

    document = fitz.open(stream=pdf_bytes, filetype="pdf")

    output_dir = PROJECT_ROOT / "outputs" / "annotated_pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Các trang đã tìm thấy hình ảnh
    pages_to_check = [3, 4, 5, 6, 8, 9]

    for page_number in pages_to_check:

        page = document[page_number - 1]

        # Tạo bản sao để đánh dấu, không sửa PDF gốc
        preview = fitz.open()
        preview.insert_pdf(
            document,
            from_page=page_number - 1,
            to_page=page_number - 1
        )

        preview_page = preview[0]

        images = page.get_images(full=True)

        for image_index, image_info in enumerate(images, start=1):

            xref = image_info[0]
            rectangles = page.get_image_rects(xref)

            for occurrence, rect in enumerate(rectangles, start=1):

                # Vẽ khung quanh ảnh
                preview_page.draw_rect(
                    rect,
                    color=(1, 0, 0),
                    width=1.5
                )

                # Đánh dấu tên ảnh
                label = f"IMG_{image_index:02d}"

                preview_page.insert_text(
                    (rect.x0, max(12, rect.y0 - 4)),
                    label,
                    fontsize=9,
                    color=(1, 0, 0)
                )

        output_file = (
            output_dir / f"page_{page_number:02d}_marked.png"
        )

        pix = preview_page.get_pixmap(
            matrix=fitz.Matrix(1.5, 1.5),
            alpha=False
        )

        pix.save(str(output_file))

        preview.close()

        print("Đã tạo:", output_file.name)

    document.close()

    print("\nHOÀN THÀNH!")
    print("Thư mục:", output_dir)


if __name__ == "__main__":
    create_preview()
