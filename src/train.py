
import json
import shutil
import tensorflow as tf

from tensorflow import keras

from src.config import (
    MODEL_DIR,
    OUTPUT_DIR,
    BEST_MODEL_PATH,
    FINAL_MODEL_PATH,
    EPOCHS_STAGE1,
    EPOCHS_STAGE2,
    EARLY_STOPPING_PATIENCE,
    BACKBONE,
    IMAGE_SIZE,
)

from src.data_loader import load_data, load_train_class_weights

from src.model import (
    build_model,
    compile_stage1,
    unfreeze_model,
)


def create_callbacks(checkpoint_path, log_path, best_val_loss=None):
    """
    Tao callbacks de luu mo hinh va theo doi qua trinh huan luyen.

    best_val_loss: val_loss tot nhat cua giai doan truoc. Giai doan 2 chi
    ghi de mo hinh khi THUC SU tot hon giai doan 1 (truoc day checkpoint
    bat dau tu vo cung nen luon ghi de, ke ca khi kem hon).
    """

    return [
        keras.callbacks.ModelCheckpoint(
            filepath=str(checkpoint_path),
            monitor="val_loss",
            save_best_only=True,
            mode="min",
            initial_value_threshold=best_val_loss,
            verbose=1
        ),

        # Tap val nho (~130 anh) nen val_loss dao dong -> kien nhan hon
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=EARLY_STOPPING_PATIENCE,
            restore_best_weights=True,
            mode="min",
            verbose=1
        ),

        # Truoc day factor=0.2, patience=2 lam LR giam ve ~0 chi sau vai epoch
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=3,
            min_lr=1e-6,
            verbose=1
        ),

        keras.callbacks.CSVLogger(
            str(log_path),
            append=False
        )
    ]


def save_history(history, file_path):
    """
    Luu lich su huan luyen thanh JSON.
    """

    data = {
        key: [float(value) for value in values]
        for key, values in history.history.items()
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def train_stage1(model, train_data, val_data, class_weight=None):
    """
    Giai doan 1: Feature Extraction.
    Dong bang backbone va huan luyen lop phan loai.
    """

    print("\n" + "=" * 60)
    print("GIAI DOAN 1: FEATURE EXTRACTION")
    print("=" * 60)

    # Compile voi learning rate giai doan 1
    model = compile_stage1(model)

    callbacks = create_callbacks(
        BEST_MODEL_PATH,
        OUTPUT_DIR / "stage1_training.csv"
    )

    history = model.fit(
        train_data,
        validation_data=val_data,
        epochs=EPOCHS_STAGE1,
        callbacks=callbacks,
        class_weight=class_weight,
        verbose=1
    )

    save_history(
        history,
        OUTPUT_DIR / "stage1_history.json"
    )

    print("\nHoan thanh giai doan 1!")

    return history


def train_stage2(model, train_data, val_data, class_weight=None,
                 best_val_loss=None):
    """
    Giai doan 2: Fine-tuning.
    Mo bang cac lop cuoi cua backbone.
    """

    print("\n" + "=" * 60)
    print("GIAI DOAN 2: FINE-TUNING")
    print("=" * 60)

    # Mo bang cac lop cuoi va compile lai
    model = unfreeze_model(model)

    trainable_params = sum(
        int(tf.size(variable).numpy())
        for variable in model.trainable_variables
    )

    print(
        "\nSo tham so co the huan luyen:",
        trainable_params
    )

    callbacks = create_callbacks(
        FINAL_MODEL_PATH,
        OUTPUT_DIR / "stage2_training.csv",
        best_val_loss=best_val_loss
    )

    history = model.fit(
        train_data,
        validation_data=val_data,
        epochs=EPOCHS_STAGE2,
        callbacks=callbacks,
        class_weight=class_weight,
        verbose=1
    )

    save_history(
        history,
        OUTPUT_DIR / "stage2_history.json"
    )

    print("\nHoan thanh giai doan 2!")

    return history


def main():

    # Tao thu muc neu chua ton tai
    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 60)
    print("HUAN LUYEN CNN PHAN LOAI BENH LA LUA")
    print("=" * 60)

    # 1. DOC DU LIEU

    print("\n[1] DANG DOC DU LIEU...")

    train_data, val_data, test_data, class_names = load_data()

    num_classes = len(class_names)

    # Du lieu goc mat can bang lop -> dung trong so lop
    class_weight = load_train_class_weights()
    print(
        "\nTrong so lop:",
        {class_names[k]: round(v, 3) for k, v in class_weight.items()}
    )

    print("\nSo lop:", num_classes)

    print("\nDanh sach cac lop:")

    for index, class_name in enumerate(class_names):
        print(f"{index}: {class_name}")

    # 2. KHOI TAO MO HINH

    print("\n[2] DANG KHOI TAO MO HINH...")

    model, base_model = build_model(
        num_classes=num_classes
    )

    print("\nKhoi tao mo hinh thanh cong!")
    print("Backbone:", BACKBONE, "| Kich thuoc anh:", IMAGE_SIZE)

    print("\nTong so tham so:", model.count_params())
    # 3. GIAI DOAN 1

    print("\n[3] BAT DAU GIAI DOAN 1...")

    history1 = train_stage1(
        model,
        train_data,
        val_data,
        class_weight
    )
    # 4. NAP MO HINH TOT NHAT GIAI DOAN 1

    print("\n[4] NAP MO HINH TOT NHAT GIAI DOAN 1...")

    model = keras.models.load_model(BEST_MODEL_PATH)

    # Dùng mô hình tốt nhất Stage 1 làm phương án an toàn ban đầu.
    # Nếu Stage 2 không cải thiện val_loss, file FINAL vẫn hợp lệ.
    shutil.copy2(BEST_MODEL_PATH, FINAL_MODEL_PATH)

    best_val_loss = min(history1.history["val_loss"])

    print("\nNap mo hinh giai doan 1 thanh cong!")
    print(f"val_loss tot nhat giai doan 1: {best_val_loss:.4f}")
    # 5. GIAI DOAN 2

    print("\n[5] BAT DAU GIAI DOAN 2...")

    train_stage2(
        model,
        train_data,
        val_data,
        class_weight,
        best_val_loss
    )
    # 6. KET THUC

    print("\n" + "=" * 60)
    print("HOAN THANH HUAN LUYEN!")
    print("=" * 60)

    print("\nMo hinh tot nhat giai doan 1:")
    print(BEST_MODEL_PATH)

    print("\nMo hinh tot nhat giai doan 2:")
    print(FINAL_MODEL_PATH)

    print("\nTap Test chua duoc su dung trong huan luyen.")

    print("\nHay su dung evaluate.py de danh gia tren tap Test.")


if __name__ == "__main__":
    main()
