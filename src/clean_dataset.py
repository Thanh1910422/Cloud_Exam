import hashlib
import csv
from pathlib import Path
from collections import defaultdict
# 1. CẤU HÌNH DATASET

# Thư mục gốc của dự án
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Đường dẫn Dataset
DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "Rice_Leaf_AUG"
)

OUTPUT_PATH = Path("output")
OUTPUT_PATH.mkdir(exist_ok=True)

REPORT_PATH = OUTPUT_PATH / "duplicate_report.csv"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp"
}

# 2. TÍNH HASH ẢNH

def calculate_hash(image_path):

    sha256 = hashlib.sha256()

    with open(image_path, "rb") as file:

        for chunk in iter(
            lambda: file.read(4096), b""
        ):
            sha256.update(chunk)

    return sha256.hexdigest()

# 3. QUÉT DATASET

def scan_dataset():

    hash_groups = defaultdict(list)

    total_images = 0

    print("\nĐANG QUÉT DATASET...\n")

    for class_folder in DATASET_PATH.iterdir():

        if not class_folder.is_dir():
            continue

        class_name = class_folder.name

        for image_path in class_folder.rglob("*"):

            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            try:

                image_hash = calculate_hash(image_path)

                hash_groups[image_hash].append({
                    "class_name": class_name,
                    "image_path": str(image_path)
                })

                total_images += 1

            except Exception as error:

                print("Lỗi:", image_path, error)

    return hash_groups, total_images

# 4. PHÂN LOẠI ẢNH TRÙNG

def analyze_duplicates(hash_groups):

    duplicate_groups = []

    same_class_groups = 0
    cross_class_groups = 0

    for image_hash, images in hash_groups.items():

        if len(images) <= 1:
            continue

        classes = set(
            image["class_name"]
            for image in images
        )

        if len(classes) == 1:

            duplicate_type = "DUPLICATE_SAME_CLASS"
            same_class_groups += 1

        else:

            duplicate_type = "DUPLICATE_DIFFERENT_CLASSES"
            cross_class_groups += 1

        duplicate_groups.append({
            "hash": image_hash,
            "type": duplicate_type,
            "images": images
        })

    return (
        duplicate_groups,
        same_class_groups,
        cross_class_groups
    )

# 5. XUẤT BÁO CÁO CSV

def export_report(duplicate_groups):

    with open(
        REPORT_PATH,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Duplicate_Type",
            "Image_Hash",
            "Class_Name",
            "Image_Path"
        ])

        for group in duplicate_groups:

            for image in group["images"]:

                writer.writerow([
                    group["type"],
                    group["hash"],
                    image["class_name"],
                    image["image_path"]
                ])
# 6. CHƯƠNG TRÌNH CHÍNH

def main():

    if not DATASET_PATH.exists():

        print("KHÔNG TÌM THẤY DATASET!")
        print("Đường dẫn:", DATASET_PATH.resolve())
        return

    hash_groups, total_images = scan_dataset()

    (
        duplicate_groups,
        same_class,
        cross_class
    ) = analyze_duplicates(hash_groups)

    duplicate_images = sum(
        len(group["images"])
        for group in duplicate_groups
    )

    print("\n" + "=" * 55)
    print("KẾT QUẢ KIỂM TRA DATASET")
    print("=" * 55)

    print("Tổng số ảnh:", total_images)

    print("Số nhóm ảnh trùng:", len(duplicate_groups))

    print("Số nhóm trùng cùng lớp:", same_class)

    print("Số nhóm trùng khác lớp:", cross_class)

    print("Tổng số file thuộc nhóm trùng:", duplicate_images)

    export_report(duplicate_groups)

    print("\nĐÃ XUẤT BÁO CÁO:")
    print(REPORT_PATH.resolve())

    print("\nHOÀN THÀNH!")


if __name__ == "__main__":
    main()