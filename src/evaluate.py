import json
import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
import keras

from pathlib import Path
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
)

from src.config import (
    FINAL_MODEL_PATH,
    OUTPUT_DIR,
    REPORT_DIR,
    PLOT_DIR,
    USE_TTA,
)

from src.data_loader import load_data
from src.image_utils import predict_with_tta


def evaluate_model():
    print("=" * 60)
    print("DANH GIA MO HINH CNN PHAN LOAI BENH LA LUA")
    print("=" * 60)

    # Tao thu muc luu ket qua
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Kiem tra mo hinh
    if not FINAL_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Khong tim thay mo hinh: {FINAL_MODEL_PATH}"
        )

    # 2. Nap du lieu
    train_data, val_data, test_data, class_names = load_data()

    print("\nSo lop:", len(class_names))
    print("So anh Testing:",
          sum(1 for _ in test_data.unbatch()))

    # 3. Nap mo hinh tot nhat sau Fine-tuning
    print("\nDang nap mo hinh...")

    model = keras.models.load_model(FINAL_MODEL_PATH)

    print("Nap mo hinh thanh cong!")

    # 4. Danh gia loss va accuracy
    print("\nDANG DANH GIA TREN TAP TESTING...")

    test_loss, test_accuracy = model.evaluate(
        test_data,
        verbose=1
    )

    # 5. Du doan nhan
    # Nhan dang one-hot -> chuyen ve chi so lop
    y_true = []
    y_prob = []

    for images, labels in test_data:
        y_true.append(np.argmax(labels.numpy(), axis=1))
        y_prob.append(predict_with_tta(model, images.numpy(), USE_TTA))

    y_true = np.concatenate(y_true)
    y_prob = np.concatenate(y_prob)

    y_pred = np.argmax(y_prob, axis=1)

    # 6. Tinh cac chi so
    accuracy = accuracy_score(y_true, y_pred)

    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(class_names))),
        target_names=class_names,
        output_dict=True,
        zero_division=0
    )

    report_text = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(class_names))),
        target_names=class_names,
        zero_division=0
    )

    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=list(range(len(class_names)))
    )

    # 7. In ket qua
    print("\n" + "=" * 60)
    print("KET QUA DANH GIA")
    print("=" * 60)

    print(f"Test Loss: {test_loss:.4f}")
    print(f"Test Accuracy (khong TTA): {test_accuracy * 100:.2f}%")
    print(f"Test Accuracy (TTA={USE_TTA}): {accuracy * 100:.2f}%")

    print("\nCLASSIFICATION REPORT:")
    print(report_text)

    print("\nCONFUSION MATRIX:")
    print(cm)

    # 8. Luu classification report
    report_file = REPORT_DIR / "classification_report.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=4
        )

    text_file = REPORT_DIR / "classification_report.txt"

    with open(text_file, "w", encoding="utf-8") as f:
        f.write("KET QUA DANH GIA MO HINH CNN\n\n")
        f.write(f"Test Loss: {test_loss:.4f}\n")
        f.write(f"Test Accuracy (khong TTA): {test_accuracy * 100:.2f}%\n")
        f.write(f"Test Accuracy (TTA={USE_TTA}): {accuracy * 100:.2f}%\n\n")
        f.write(report_text)

    # 9. Ve va luu Confusion Matrix
    fig, ax = plt.subplots(figsize=(10, 8))

    display = ConfusionMatrixDisplay(
        confusion_matrix=cm,
        display_labels=class_names
    )

    display.plot(
        ax=ax,
        cmap="Blues",
        xticks_rotation=45,
        values_format="d",
        colorbar=False
    )

    ax.set_title("Confusion Matrix - Rice Leaf Disease")
    ax.set_xlabel("Predicted Label")
    ax.set_ylabel("True Label")

    plt.tight_layout()

    cm_path = PLOT_DIR / "confusion_matrix.png"

    plt.savefig(
        cm_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close(fig)

    # 10. Luu ma tran nham lan dang CSV
    np.savetxt(
        REPORT_DIR / "confusion_matrix.csv",
        cm,
        delimiter=",",
        fmt="%d"
    )

    print("\nDA LUU KET QUA:")
    print("Classification Report:", text_file)
    print("Report JSON:", report_file)
    print("Confusion Matrix:", cm_path)

    print("\nHOAN THANH DANH GIA MO HINH!")


if __name__ == "__main__":
    evaluate_model()
