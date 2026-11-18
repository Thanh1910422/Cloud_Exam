
import csv
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.config import SOURCE_DIR, SUPPORTED_EXTENSIONS


def analyze_image(image_path):
    """Đọc và lấy thông tin cơ bản của ảnh."""
    try:
        with Image.open(image_path) as img:
            img.load()

            return {
                "status": "OK",
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "channels": len(img.getbands()),
            }

    except (UnidentifiedImageError, OSError, ValueError) as error:
        return {
            "status": "ERROR",
            "width": None,
            "height": None,
            "format": None,
            "mode": None,
            "channels": None,
            "error": str(error),
        }


def main():
    print("=" * 65)
    print("PHAN TICH CHAT LUONG BO DU LIEU LA LUA")
    print("=" * 65)

    if not SOURCE_DIR.exists():
        print(f"KHONG TIM THAY DUONG DAN: {SOURCE_DIR}")
        return

    class_folders = sorted(
        folder for folder in SOURCE_DIR.iterdir()
        if folder.is_dir()
    )

    if not class_folders:
        print("Khong tim thay thu muc lop!")
        return

    print(f"\nDuong dan dataset: {SOURCE_DIR}")
    print(f"So lop: {len(class_folders)}")

    total_images = 0
    valid_images = 0
    invalid_images = 0

    class_counts = Counter()
    image_sizes = Counter()
    image_modes = Counter()
    image_formats = Counter()

    report_rows = []

    for class_folder in class_folders:
        images = sorted(
            path for path in class_folder.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        print(f"\nLop: {class_folder.name} ({len(images)} anh)")

        class_counts[class_folder.name] = len(images)

        for image_path in images:
            total_images += 1

            info = analyze_image(image_path)

            row = {
                "class_name": class_folder.name,
                "image_path": str(image_path),
                **info,
            }

            report_rows.append(row)

            if info["status"] == "OK":
                valid_images += 1

                image_sizes[
                    f'{info["width"]}x{info["height"]}'
                ] += 1

                image_modes[info["mode"]] += 1
                image_formats[info["format"]] += 1

            else:
                invalid_images += 1
                print(f"Anh loi: {image_path}")

    # Tạo thư mục output
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Xuất báo cáo CSV
    report_path = output_dir / "image_quality_report.csv"

    fieldnames = [
        "class_name",
        "image_path",
        "status",
        "width",
        "height",
        "format",
        "mode",
        "channels",
        "error",
    ]

    with report_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )
        writer.writeheader()
        writer.writerows(report_rows)

    # Hiển thị kết quả
    print("\n" + "=" * 65)
    print("KET QUA PHAN TICH DATASET")
    print("=" * 65)

    print(f"Tong so anh: {total_images}")
    print(f"Anh hop le: {valid_images}")
    print(f"Anh loi: {invalid_images}")

    print("\nTHONG KE THEO LOP:")
    for class_name, count in class_counts.items():
        print(f"{class_name}: {count}")

    print("\nTHONG KE KICH THUOC ANH:")
    for size, count in image_sizes.most_common():
        print(f"{size}: {count} anh")

    print("\nTHONG KE CHE DO MAU:")
    for mode, count in image_modes.items():
        print(f"{mode}: {count} anh")

    print("\nTHONG KE DINH DANG:")
    for image_format, count in image_formats.items():
        print(f"{image_format}: {count} anh")

    print("\n" + "=" * 65)
    print("HOAN THANH PHAN TICH!")
    print(f"Bao cao da luu tai: {report_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
