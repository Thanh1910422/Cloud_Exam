
import sys
import json
from pathlib import Path

import fitz
from PIL import Image
from io import BytesIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.storage import storage


def inspect_pdf_images():

    storage_path = (
        "exams/2/exam_document/"
        "1fdb079e56be454a8164b9a7cda27ec4_H10000.pdf"
    )

    print("Đang tải PDF...")

    pdf_bytes = storage.download(storage_path)

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    image_dir = PROJECT_ROOT / "outputs" / "pdf_images"

    results = []

    for page_index in range(len(document)):

        page = document[page_index]
        page_number = page_index + 1

        images = page.get_images(full=True)

        for image_index, image_info in enumerate(images, start=1):

            xref = image_info[0]

            image_data = document.extract_image(xref)
            image_bytes = image_data["image"]

            with Image.open(BytesIO(image_bytes)) as img:
                width, height = img.size

            rectangles = page.get_image_rects(xref)

            for occurrence, rect in enumerate(rectangles, start=1):

                results.append({
                    "page": page_number,
                    "image_index": image_index,
                    "occurrence": occurrence,
                    "filename": (
                        f"page_{page_number:02d}_"
                        f"image_{image_index:02d}."
                        f"{image_data['ext']}"
                    ),
                    "width": width,
                    "height": height,
                    "x0": round(rect.x0, 2),
                    "y0": round(rect.y0, 2),
                    "x1": round(rect.x1, 2),
                    "y1": round(rect.y1, 2)
                })

    document.close()

    output_file = PROJECT_ROOT / "outputs" / "image_manifest.json"

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=4)

    print("\n--- DANH SÁCH HÌNH ẢNH ---")

    for item in results:
        print(
            f"Trang {item['page']} | "
            f"{item['filename']} | "
            f"Kích thước: {item['width']}x{item['height']} | "
            f"Vị trí: ({item['x0']}, {item['y0']})"
        )

    print("\nTổng số vị trí hình ảnh:", len(results))
    print("File JSON:", output_file)


if __name__ == "__main__":
    inspect_pdf_images()
