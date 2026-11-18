
import json
from pathlib import Path

import numpy as np
import tensorflow as tf

from src.config import (
    ROOT_DIR,
    TRAIN_MANIFEST,
    VAL_MANIFEST,
    TEST_MANIFEST,
    CLASS_NAMES_PATH,
    IMAGE_SIZE,
    BATCH_SIZE,
    SEED,
)
from src.image_utils import load_image_array

AUTOTUNE = tf.data.AUTOTUNE


def load_json(file_path):
    """Đọc dữ liệu từ file JSON."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(path):
    """Manifest lưu đường dẫn tương đối so với thư mục dự án."""
    path = Path(path)
    return str(path if path.is_absolute() else ROOT_DIR / path)


def load_image(image_path, label):
    """
    Đọc ảnh bằng hàm dùng chung với predict.py/app.py:
    xoay theo EXIF, chuyển RGB, resize có khử răng cưa.
    Trả về uint8 [0, 255]; model.py sẽ preprocess đúng một lần.
    """

    image = tf.numpy_function(
        lambda path: load_image_array(path.decode("utf-8")),
        [image_path],
        tf.uint8
    )

    image.set_shape([IMAGE_SIZE[0], IMAGE_SIZE[1], 3])

    label = tf.cast(label, tf.int32)

    return image, label


def create_dataset(records, num_classes, training=False):
    """Tạo TensorFlow Dataset từ danh sách ảnh."""

    image_paths = [
        resolve_path(record["path"]) for record in records
    ]

    labels = [
        record["label"] for record in records
    ]

    dataset = tf.data.Dataset.from_tensor_slices(
        (image_paths, labels)
    )

    # Giải mã + resize một lần rồi cache (uint8) trong RAM,
    # không phải đọc lại ảnh 1600x1200 ở mỗi epoch.
    dataset = dataset.map(
        load_image,
        num_parallel_calls=AUTOTUNE
    ).cache()

    if training:
        dataset = dataset.shuffle(
            buffer_size=len(records),
            seed=SEED,
            reshuffle_each_iteration=True
        )

    dataset = dataset.batch(BATCH_SIZE)

    # Ảnh float32 + nhãn one-hot (để dùng label smoothing trong loss)
    def to_model_format(images, labels):
        return (
            tf.cast(images, tf.float32),
            tf.one_hot(labels, num_classes)
        )

    dataset = dataset.map(to_model_format, num_parallel_calls=AUTOTUNE)

    dataset = dataset.prefetch(AUTOTUNE)

    return dataset


def compute_class_weights(records, num_classes):
    """Trọng số lớp tỷ lệ nghịch số ảnh (dữ liệu gốc mất cân bằng)."""

    counts = np.bincount(
        [record["label"] for record in records],
        minlength=num_classes
    )
    total = counts.sum()

    return {
        label: float(total / (num_classes * count))
        for label, count in enumerate(counts)
        if count > 0
    }


def load_data():
    """Đọc và tạo ba tập dữ liệu."""

    print("Dang doc cac file JSON...")

    train_records = load_json(TRAIN_MANIFEST)
    val_records = load_json(VAL_MANIFEST)
    test_records = load_json(TEST_MANIFEST)

    class_names = load_json(CLASS_NAMES_PATH)

    print("\nSo luong anh:")
    print("Tổng số ảnh sau khi xử lý :", len(train_records) + len(val_records) + len(test_records))
    print("Training:", len(train_records))
    print("Validation:", len(val_records))
    print("Testing:", len(test_records))

    print("\nDanh sach lop:")
    for index, name in enumerate(class_names):
        print(f"{index}: {name}")

    num_classes = len(class_names)

    train_dataset = create_dataset(
        train_records,
        num_classes,
        training=True
    )

    val_dataset = create_dataset(
        val_records,
        num_classes,
        training=False
    )

    test_dataset = create_dataset(
        test_records,
        num_classes,
        training=False
    )

    return (
        train_dataset,
        val_dataset,
        test_dataset,
        class_names
    )


def load_train_class_weights():
    """Trọng số lớp tính từ tập train."""
    class_names = load_json(CLASS_NAMES_PATH)
    return compute_class_weights(
        load_json(TRAIN_MANIFEST),
        len(class_names)
    )


def check_dataset():
    """Kiểm tra kích thước ảnh và nhãn."""

    train_dataset, val_dataset, test_dataset, class_names = (
        load_data()
    )

    print("\nKIEM TRA DU LIEU DA TIEN XU LY")

    for images, labels in train_dataset.take(1):
        print("Kich thuoc batch anh:", images.shape)
        print("Kich thuoc batch nhan:", labels.shape)
        print("Gia tri pixel nho nhat:",
              float(tf.reduce_min(images)))
        print("Gia tri pixel lon nhat:",
              float(tf.reduce_max(images)))

    print("\nSo lop:", len(class_names))
    print("So batch Training:",
          tf.data.experimental.cardinality(train_dataset).numpy())
    print("So batch Validation:",
          tf.data.experimental.cardinality(val_dataset).numpy())
    print("So batch Testing:",
          tf.data.experimental.cardinality(test_dataset).numpy())

    print("\nHOAN THANH KIEM TRA DATA LOADER!")


if __name__ == "__main__":
    check_dataset()
