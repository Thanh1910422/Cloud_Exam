
from pathlib import Path

# Thư mục gốc dự án
ROOT_DIR = Path(__file__).resolve().parent.parent

# Đường dẫn dữ liệu
SOURCE_DIR = (
    ROOT_DIR
    / "data"
    / "raw"
    / "Rice_Leaf_AUG"
)

PROCESSED_DIR = ROOT_DIR / "data" / "processed"
SPLIT_DIR = ROOT_DIR / "data" / "splits"

# Thư mục lưu mô hình
MODEL_DIR = ROOT_DIR / "models"

# Thư mục lưu kết quả
OUTPUT_DIR = ROOT_DIR / "outputs"
PLOT_DIR = OUTPUT_DIR / "plots"
REPORT_DIR = OUTPUT_DIR / "reports"
PREDICTION_DIR = OUTPUT_DIR / "predictions"

# Backbone (mạng nền) cho transfer learning
# "efficientnetv2b0": chính xác hơn MobileNetV2 rõ rệt, vẫn nhẹ (~6M tham số)
# "efficientnetv2b2": chính xác hơn nữa nhưng chậm hơn (~9M tham số)
# "mobilenetv2"     : mô hình cũ, giữ lại để so sánh
BACKBONE = "efficientnetv2b0"

# Cấu hình ảnh
# Ảnh gốc 1600x1200, vết bệnh trên lá lúa rất nhỏ -> 224 làm mất chi tiết.
# 300x300 giữ được nhiều chi tiết vết bệnh hơn.
IMAGE_SIZE = (300, 300)
BATCH_SIZE = 16
SEED = 42

# Chia dữ liệu
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15

# Huấn luyện
EPOCHS_STAGE1 = 15
EPOCHS_STAGE2 = 40

LEARNING_RATE_STAGE1 = 1e-3
# 1e-5 quá nhỏ: 15 epoch gần như không thay đổi được backbone.
LEARNING_RATE_STAGE2 = 1e-4
WEIGHT_DECAY_STAGE2 = 1e-4

# Mở băng nhiều lớp hơn (cũ: 30 lớp -> chỉ chỉnh được rất ít đặc trưng).
# Đặt None để mở băng toàn bộ backbone (BatchNorm vẫn đóng băng).
FINE_TUNE_LAST_LAYERS = 150

# Label smoothing giúp mô hình bớt "quá tự tin", tổng quát tốt hơn
LABEL_SMOOTHING = 0.1

# Test-Time Augmentation khi đánh giá/dự đoán (trung bình ảnh gốc + ảnh lật)
USE_TTA = True

# Tập val nhỏ (~130 ảnh) nên val_loss dao động -> cần kiên nhẫn hơn
EARLY_STOPPING_PATIENCE = 10

# Chống rò rỉ dữ liệu (data leakage)
# Bộ Rice_Leaf_AUG chứa ảnh tăng cường "aug_*.jpg" được sinh SẴN từ ảnh gốc.
# Nếu chia ngẫu nhiên, các biến thể của cùng một chiếc lá rơi vào cả
# train lẫn test -> độ chính xác test bị thổi phồng.
AUGMENTED_PREFIX = "aug_"

# Ảnh gốc chụp liên tiếp / bản "- Copy" gần như giống hệt nhau được gom
# thành một nhóm nếu độ tương đồng cosine đặc trưng CNN >= ngưỡng này.
NEAR_DUPLICATE_THRESHOLD = 0.88

# False: chỉ dùng ảnh gốc (augmentation online trong model.py) - an toàn nhất.
# True : thêm ảnh aug_* vào TẬP TRAIN, chỉ khi ảnh gốc khớp nhất của nó
#        (top-k) đều thuộc tập train. Val/Test luôn chỉ gồm ảnh gốc.
# Bật True: tập train chỉ có ~600 ảnh gốc, thêm ảnh aug_* (đã được lọc chống
# rò rỉ bên dưới) giúp tăng lượng dữ liệu học. Cần chạy lại prepare_data.py.
USE_OFFLINE_AUG = True
AUG_MATCH_TOP_K = 3

# Định dạng ảnh
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp"
}

# File dữ liệu
TRAIN_MANIFEST = SPLIT_DIR / "train.json"
VAL_MANIFEST = SPLIT_DIR / "val.json"
TEST_MANIFEST = SPLIT_DIR / "test.json"

CLASS_NAMES_PATH = SPLIT_DIR / "class_names.json"

# File mô hình
BEST_MODEL_PATH = MODEL_DIR / "best_rice_leaf_model.keras"
FINAL_MODEL_PATH = MODEL_DIR / "final_rice_leaf_model.keras"
