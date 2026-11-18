import sys
import csv
import json
import numpy as np

from pathlib import Path
from tensorflow import keras

from src.config import (
    FINAL_MODEL_PATH,
    CLASS_NAMES_PATH,
    OUTPUT_DIR,
    USE_TTA,
)
from src.image_utils import load_image_array, to_model_input, predict_with_tta


# Cac dinh dang anh duoc ho tro khi du doan ca thu muc
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

REPORT_DIR = OUTPUT_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = REPORT_DIR / "batch_predictions.csv"


def load_class_names():
    """Doc danh sach ten lop tu file JSON."""
    if not CLASS_NAMES_PATH.exists():
        raise FileNotFoundError(
            f"Khong tim thay danh sach lop: {CLASS_NAMES_PATH}"
        )

    with open(CLASS_NAMES_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def load_trained_model():
    """Kiem tra va nap mo hinh da huan luyen."""
    if not FINAL_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Khong tim thay mo hinh: {FINAL_MODEL_PATH}\n"
            "Hay chay train.py de huan luyen va luu mo hinh truoc."
        )

    print("Dang nap mo hinh...")
    model = keras.models.load_model(FINAL_MODEL_PATH)
    print("Da nap mo hinh thanh cong!")
    return model


def preprocess_image(image_path):
    """Doc anh, chuyen RGB, resize va chuyen thanh tensor."""
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Khong tim thay anh: {image_path}")

    # Dung chung ham tien xu ly voi luc huan luyen (EXIF + resize).
    # Khong preprocess tai day vi model.py da tich hop preprocess_input.
    return to_model_input(load_image_array(image_path))


def print_prediction_details(probabilities, class_names):
    """In lop du doan, do tin cay, TOP 3 va xac suat tung lop."""
    if len(probabilities) != len(class_names):
        raise ValueError(
            "So dau ra cua mo hinh khong khop so ten lop trong class_names.json."
        )

    sorted_indices = np.argsort(probabilities)[::-1]
    best_index = int(sorted_indices[0])
    predicted_class = class_names[best_index]
    confidence = float(probabilities[best_index])

    print("\n" + "=" * 60)
    print("KET QUA DU DOAN")
    print("=" * 60)
    print("Lop du doan:", predicted_class)
    print(f"Do tin cay: {confidence * 100:.2f}%")

    print("\nTOP 3 KET QUA:")
    for rank, index in enumerate(sorted_indices[:3], start=1):
        print(
            f"{rank}. {class_names[int(index)]}: "
            f"{float(probabilities[index]) * 100:.2f}%"
        )

    print("\nXAC SUAT CUA TUNG LOP:")
    for index, class_name in enumerate(class_names):
        print(f"{class_name}: {float(probabilities[index]) * 100:.2f}%")

    return predicted_class, confidence


def predict_image(image_path, model=None, class_names=None):
    """Du doan mot anh va in day du ket qua nhu predict.py cu."""
    print("=" * 60)
    print("DU DOAN BENH LA LUA BANG CNN")
    print("=" * 60)
    print("Anh dau vao:", image_path)

    if class_names is None:
        class_names = load_class_names()
    if model is None:
        model = load_trained_model()

    image = preprocess_image(image_path)
    probabilities = predict_with_tta(model, image, USE_TTA)[0]

    result = print_prediction_details(probabilities, class_names)
    print("\nHOAN THANH DU DOAN!")
    return result


def predict_folder(folder_path):
    """Du doan tat ca anh trong thu muc va xuat ket qua CSV."""
    folder_path = Path(folder_path)

    if not folder_path.exists():
        raise FileNotFoundError(f"Khong tim thay thu muc: {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(
            f"Duong dan khong phai thu muc: {folder_path}"
        )

    image_paths = sorted(
        path for path in folder_path.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not image_paths:
        print("Khong tim thay anh trong thu muc!")
        return

    print("=" * 60)
    print("DU DOAN HANG LOAT BENH LA LUA")
    print("=" * 60)
    print(f"Thu muc: {folder_path}")
    print(f"So luong anh tim thay: {len(image_paths)}")

    class_names = load_class_names()
    model = load_trained_model()

    results = []
    success_count = 0
    error_count = 0

    for index, image_path in enumerate(image_paths, start=1):
        try:
            image = preprocess_image(image_path)
            probabilities = predict_with_tta(model, image, USE_TTA)[0]

            if len(probabilities) != len(class_names):
                raise ValueError(
                    "So dau ra cua mo hinh khong khop so ten lop."
                )

            best_index = int(np.argmax(probabilities))
            predicted_class = class_names[best_index]
            confidence = float(probabilities[best_index]) * 100

            results.append([
                str(image_path),
                predicted_class,
                f"{confidence:.2f}%"
            ])
            success_count += 1

            print(
                f"{index}/{len(image_paths)} | "
                f"{image_path.name} | "
                f"{predicted_class} | "
                f"{confidence:.2f}%"
            )

        except Exception as error:
            error_count += 1
            print(
                f"{index}/{len(image_paths)} | "
                f"LOI: {image_path.name} | {error}"
            )

    # Luu CSV, giu nguyen chuc nang cua predict_folder.py cu
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["Image Path", "Predicted Class", "Confidence"])
        writer.writerows(results)

    print("\n" + "=" * 60)
    print("KET QUA TONG KET")
    print("=" * 60)
    print(f"Tong so anh: {len(image_paths)}")
    print(f"So anh du doan thanh cong: {success_count}")
    print(f"So anh bi loi: {error_count}")
    print("\nDa luu ket qua tai:")
    print(CSV_PATH)
    print("\nHOAN THANH DU DOAN HANG LOAT!")


def main():
    """Menu chon du doan mot anh hoac ca thu muc."""
    print("\n" + "=" * 60)
    print("RICE LEAF DISEASE - PREDICTION")
    print("=" * 60)
    print("1. Du doan mot anh")
    print("2. Du doan tat ca anh trong thu muc")
    print("0. Thoat")

    choice = input("\nChon chuc nang (0/1/2): ").strip()

    try:
        if choice == "1":
            image_path = input(
                "Nhap duong dan anh la lua can du doan: "
            ).strip().strip('"')
            predict_image(image_path)

        elif choice == "2":
            folder_path = input(
                "Nhap duong dan thu muc chua anh la lua: "
            ).strip().strip('"')
            predict_folder(folder_path)

        elif choice == "0":
            print("Da thoat chuong trinh.")

        else:
            print("Lua chon khong hop le. Hay chon 0, 1 hoac 2.")

    except Exception as error:
        print("\nLOI KHI DU DOAN:")
        print(error)


if __name__ == "__main__":
    main()
