import sys
from pathlib import Path

# Thêm thư mục gốc Cloud_Exam vào đường dẫn tìm kiếm của Python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.storage import storage


def test_storage_connection():
    try:
        result = storage.list()

        print("KET NOI SUPABASE STORAGE THANH CONG!")
        print("Danh sach file:", result)

    except Exception as e:
        print("KET NOI THAT BAI!")
        print("Chi tiet loi:", e)


if __name__ == "__main__":
    test_storage_connection()