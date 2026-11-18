"""
Chuẩn bị và chia bộ dữ liệu bệnh lá lúa THEO NHÓM để tránh rò rỉ dữ liệu.

Vấn đề của cách chia cũ (train_test_split ngẫu nhiên trên toàn bộ ảnh):
1. ~75% ảnh là "aug_*.jpg" - biến thể (xoay/lật/zoom/dịch) sinh sẵn từ ảnh
   gốc. Biến thể của cùng một chiếc lá nằm ở cả train, val và test.
2. Nhiều ảnh gốc là ảnh chụp liên tiếp hoặc bản "- Copy" gần giống hệt nhau;
   SHA256 chỉ phát hiện được file trùng từng byte.
=> Test accuracy phản ánh khả năng "nhớ ảnh" chứ không phải khả năng tổng quát.

Cách xử lý mới:
- Loại file trùng tuyệt đối bằng SHA256 (như cũ).
- Gom ảnh gốc gần trùng thành nhóm (đặc trưng MobileNetV2 + cosine).
- Chia 70/15/15 theo NHÓM, phân tầng theo lớp: một nhóm chỉ thuộc một tập.
- Val/Test chỉ gồm ảnh gốc (phân phối ảnh thật).
- Ảnh aug_*: mặc định bỏ (model.py đã augmentation online). Nếu bật
  USE_OFFLINE_AUG, chỉ đưa vào train khi ảnh gốc khớp nhất đều thuộc train.
"""

import json
import hashlib
import random
from collections import defaultdict, Counter

import numpy as np

from src.config import (
    ROOT_DIR,
    SOURCE_DIR,
    SPLIT_DIR,
    SEED,
    TRAIN_RATIO,
    VAL_RATIO,
    TEST_RATIO,
    SUPPORTED_EXTENSIONS,
    AUGMENTED_PREFIX,
    NEAR_DUPLICATE_THRESHOLD,
    USE_OFFLINE_AUG,
    AUG_MATCH_TOP_K,
)
from src.image_utils import load_image_array

SPLITS = ("train", "val", "test")


def calculate_hash(file_path):
    """Tính mã SHA256 để nhận diện ảnh trùng tuyệt đối."""
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def to_manifest_path(image_path):
    """Lưu đường dẫn tương đối so với thư mục dự án (dễ di chuyển dự án)."""
    try:
        return image_path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return str(image_path.resolve())


def collect_images():
    """Thu thập ảnh và nhóm theo mã SHA256."""

    hash_groups = defaultdict(list)
    class_names = sorted(
        folder.name
        for folder in SOURCE_DIR.iterdir()
        if folder.is_dir()
    )

    for label, class_name in enumerate(class_names):
        class_dir = SOURCE_DIR / class_name

        for image_path in sorted(class_dir.rglob("*")):
            if (
                image_path.is_file()
                and image_path.suffix.lower() in SUPPORTED_EXTENSIONS
            ):
                hash_groups[calculate_hash(image_path)].append({
                    "path": to_manifest_path(image_path),
                    "label": label,
                    "class_name": class_name,
                    "augmented": image_path.name.startswith(
                        AUGMENTED_PREFIX
                    ),
                })

    return hash_groups, class_names


def remove_duplicates(hash_groups):
    """Loại ảnh trùng cùng nhãn; bỏ qua nhóm trùng khác nhãn."""

    records = []
    duplicate_removed = 0
    cross_class_groups = []

    for group in hash_groups.values():
        labels = {item["label"] for item in group}

        # Ảnh giống nhau nhưng thuộc các lớp khác nhau:
        # Không tự ý chọn nhãn, đưa vào danh sách kiểm tra.
        if len(labels) > 1:
            cross_class_groups.append(group)
            continue

        # Ưu tiên giữ ảnh gốc làm đại diện của nhóm.
        group = sorted(group, key=lambda item: item["augmented"])
        records.append(group[0])
        duplicate_removed += len(group) - 1

    print("\nKET QUA XU LY ANH TRUNG (SHA256)")
    print("So anh trung cung nhan da loai:", duplicate_removed)
    print("So nhom trung khac nhan can kiem tra:", len(cross_class_groups))

    if cross_class_groups:
        report_path = SPLIT_DIR / "cross_class_duplicates.json"
        save_json(report_path, cross_class_groups)
        print("Danh sach anh can kiem tra:", report_path)

    return records


def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ---------------------------------------------------------------------------
# Đặc trưng ảnh để phát hiện ảnh gần trùng
# ---------------------------------------------------------------------------

def build_feature_extractor():
    import keras

    model = keras.applications.MobileNetV2(
        include_top=False,
        weights="imagenet",
        pooling="avg",
        input_shape=(224, 224, 3),
    )

    def extract(images):
        x = keras.applications.mobilenet_v2.preprocess_input(
            np.stack(images).astype(np.float32)
        )
        features = model.predict(x, batch_size=64, verbose=0)
        return features / np.linalg.norm(features, axis=1, keepdims=True)

    return extract


def load_for_features(record):
    return load_image_array(ROOT_DIR / record["path"], (224, 224))


def group_originals(originals, features, threshold):
    """Union-Find: gom các ảnh gốc có cosine >= threshold vào cùng nhóm."""
    parent = list(range(len(originals)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    similarity = features @ features.T
    rows, cols = np.where(np.triu(similarity >= threshold, k=1))

    for i, j in zip(rows, cols):
        parent[find(i)] = find(j)

    return [find(i) for i in range(len(originals))]


def assign_groups_to_splits(group_sizes, rng):
    """Phân các nhóm của MỘT lớp vào train/val/test sát tỷ lệ 70/15/15."""
    ratios = {"train": TRAIN_RATIO, "val": VAL_RATIO, "test": TEST_RATIO}
    total = sum(group_sizes.values())
    targets = {name: ratios[name] * total for name in SPLITS}
    counts = {name: 0 for name in SPLITS}

    group_ids = list(group_sizes)
    rng.shuffle(group_ids)
    # Xếp nhóm lớn trước để các nhóm nhỏ lấp phần còn thiếu chính xác hơn.
    group_ids.sort(key=lambda g: group_sizes[g], reverse=True)

    assignment = {}
    for group_id in group_ids:
        split = max(
            SPLITS,
            key=lambda s: (targets[s] - counts[s]) / targets[s]
        )
        assignment[group_id] = split
        counts[split] += group_sizes[group_id]

    return assignment


def build_splits(records, class_names):
    rng = random.Random(SEED)
    extract = build_feature_extractor()
    splits = {name: [] for name in SPLITS}
    aug_stats = Counter()

    for label, class_name in enumerate(class_names):
        class_records = [r for r in records if r["label"] == label]
        originals = [r for r in class_records if not r["augmented"]]
        augmented = [r for r in class_records if r["augmented"]]

        print(f"\n[{class_name}] anh goc: {len(originals)}, "
              f"anh aug: {len(augmented)}")

        original_images = [load_for_features(r) for r in originals]
        original_features = extract(original_images)

        roots = group_originals(
            originals, original_features, NEAR_DUPLICATE_THRESHOLD
        )
        group_names = {
            root: f"{label}_{index:04d}"
            for index, root in enumerate(dict.fromkeys(roots))
        }
        for record, root in zip(originals, roots):
            record["group"] = group_names[root]

        group_sizes = Counter(r["group"] for r in originals)
        assignment = assign_groups_to_splits(group_sizes, rng)

        print(f"  So nhom (sau khi gom anh gan trung): {len(group_sizes)}")

        for record in originals:
            splits[assignment[record["group"]]].append(record)

        if not (USE_OFFLINE_AUG and augmented):
            aug_stats["bo_qua"] += len(augmented)
            continue

        # So khớp ảnh aug với ảnh gốc (kể cả bản lật/xoay của ảnh gốc,
        # vì ảnh aug được sinh bằng các phép biến đổi này).
        variants = [
            original_features,
            extract([img[:, ::-1] for img in original_images]),
            extract([img[::-1] for img in original_images]),
            extract([np.rot90(img) for img in original_images]),
            extract([np.rot90(img, 3) for img in original_images]),
        ]
        aug_features = extract([load_for_features(r) for r in augmented])
        similarity = np.max(
            [aug_features @ v.T for v in variants], axis=0
        )
        top_k = np.argsort(-similarity, axis=1)[:, :AUG_MATCH_TOP_K]

        for record, neighbours in zip(augmented, top_k):
            matched_splits = {
                assignment[originals[i]["group"]] for i in neighbours
            }
            record["group"] = originals[neighbours[0]]["group"]

            if matched_splits == {"train"}:
                splits["train"].append(record)
                aug_stats["dua_vao_train"] += 1
            else:
                # Có thể là biến thể của ảnh val/test -> loại bỏ.
                aug_stats["loai_do_nghi_ro_ri"] += 1

    return splits, aug_stats


def verify_no_leakage(splits):
    groups = {
        name: {r["group"] for r in records}
        for name, records in splits.items()
    }
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        overlap = groups[a] & groups[b]
        if overlap:
            raise RuntimeError(
                f"Ro ri du lieu: {len(overlap)} nhom nam o ca {a} va {b}"
            )

    for name in ("val", "test"):
        if any(r["augmented"] for r in splits[name]):
            raise RuntimeError(f"Tap {name} chua anh aug_*")

    print("\nKiem tra ro ri: KHONG co nhom nao nam o nhieu tap.")


def split_dataset(records, class_names):
    """Chia dữ liệu 70/15/15 theo nhóm, phân tầng theo lớp."""

    splits, aug_stats = build_splits(records, class_names)
    verify_no_leakage(splits)

    rng = random.Random(SEED)
    for name in SPLITS:
        rng.shuffle(splits[name])
        save_json(SPLIT_DIR / f"{name}.json", splits[name])

    save_json(SPLIT_DIR / "class_names.json", class_names)

    print("\nKET QUA CHIA DU LIEU (THEO NHOM)")
    print("Training:", len(splits["train"]))
    print("Validation:", len(splits["val"]))
    print("Testing:", len(splits["test"]))
    print("Anh aug:", dict(aug_stats))

    for name in SPLITS:
        print(f"\n{name} theo tung lop:")
        counts = Counter(r["label"] for r in splits[name])
        for label, class_name in enumerate(class_names):
            print(f"{class_name}: {counts[label]}")


def main():
    print("=" * 60)
    print("CHUAN BI VA CHIA BO DU LIEU BENH LA LUA")
    print("=" * 60)

    if not SOURCE_DIR.exists():
        raise FileNotFoundError(
            f"Khong tim thay thu muc: {SOURCE_DIR}"
        )

    SPLIT_DIR.mkdir(parents=True, exist_ok=True)

    hash_groups, class_names = collect_images()

    print("\nSo lop:", len(class_names))
    print("Tong so nhom anh theo hash:", len(hash_groups))

    records = remove_duplicates(hash_groups)

    if not records:
        raise ValueError("Khong co anh hop le de chia du lieu.")

    split_dataset(records, class_names)

    print("\nHOAN THANH GIAI DOAN 2!")


if __name__ == "__main__":
    main()
