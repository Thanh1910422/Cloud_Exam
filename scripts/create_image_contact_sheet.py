
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent

IMAGE_DIR = PROJECT_ROOT / "outputs" / "pdf_images"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "image_contact_sheet.jpg"

image_files = sorted([
    path for path in IMAGE_DIR.iterdir()
    if path.suffix.lower() in [".jpg", ".jpeg", ".png"]
])

if not image_files:
    print("Không tìm thấy hình ảnh!")
    raise SystemExit

# Kích thước mỗi ô
CELL_WIDTH = 220
CELL_HEIGHT = 200
IMAGE_WIDTH = 190
IMAGE_HEIGHT = 155

COLUMNS = 4
ROWS = (len(image_files) + COLUMNS - 1) // COLUMNS

sheet = Image.new(
    "RGB",
    (COLUMNS * CELL_WIDTH, ROWS * CELL_HEIGHT),
    "white"
)

draw = ImageDraw.Draw(sheet)

for index, image_path in enumerate(image_files):

    row = index // COLUMNS
    col = index % COLUMNS

    x = col * CELL_WIDTH
    y = row * CELL_HEIGHT

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail((IMAGE_WIDTH, IMAGE_HEIGHT))

        image_x = x + (CELL_WIDTH - img.width) // 2
        image_y = y + 5

        sheet.paste(img, (image_x, image_y))

    draw.text(
        (x + 10, y + 165),
        image_path.name,
        fill="black"
    )

sheet.save(OUTPUT_FILE, quality=95)

print("Đã tạo ảnh tổng hợp!")
print("Tổng số ảnh:", len(image_files))
print("File:", OUTPUT_FILE)
