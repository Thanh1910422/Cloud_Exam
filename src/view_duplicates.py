import pandas as pd
import matplotlib.pyplot as plt

from PIL import Image
from pathlib import Path

# Đọc báo cáo
REPORT = Path("output/duplicate_report.csv")

df = pd.read_csv(REPORT)

# Chỉ xem ảnh trùng cùng lớp
df = df[df["Duplicate_Type"] == "DUPLICATE_SAME_CLASS"]

# Gom nhóm theo mã hash
groups = list(df.groupby("Image_Hash"))

print("Số nhóm ảnh trùng:", len(groups))

for group_number, (image_hash, group) in enumerate(groups, 1):

    paths = group["Image_Path"].tolist()
    class_name = group["Class_Name"].iloc[0]

    fig, axes = plt.subplots(1, len(paths), figsize=(10, 4))

    if len(paths) == 1:
        axes = [axes]

    for ax, path in zip(axes, paths):

        image = Image.open(path).convert("RGB")

        ax.imshow(image)
        ax.set_title(Path(path).name)
        ax.axis("off")

    fig.suptitle(
        f"Nhóm {group_number} - {class_name}",
        fontsize=13
    )

    plt.tight_layout()
    plt.show()