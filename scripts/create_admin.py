
import getpass
import re

from werkzeug.security import generate_password_hash
from config.database import get_connection


def main():
    print("\n===== TAO TAI KHOAN ADMIN HSK EXAM =====\n")

    full_name = input("Nhap ho va ten Admin: ").strip()
    email = input("Nhap email Admin: ").strip().lower()
    password = getpass.getpass("Nhap mat khau: ")
    confirm_password = getpass.getpass("Nhap lai mat khau: ")

    if not full_name or not email or not password:
        print("Loi: Vui long nhap day du thong tin.")
        return

    if len(full_name) > 150:
        print("Loi: Ho ten khong duoc vuot qua 150 ky tu.")
        return

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        print("Loi: Email khong hop le.")
        return

    if len(password) < 8:
        print("Loi: Mat khau phai co it nhat 8 ky tu.")
        return

    if password != confirm_password:
        print("Loi: Hai mat khau khong khop.")
        return

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            # Kiem tra email da ton tai
            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )

            if cursor.fetchone():
                print("Loi: Email nay da ton tai trong he thong.")
                connection.rollback()
                return

            # Lay role admin
            cursor.execute(
                "SELECT id FROM roles WHERE role_name = %s",
                ("admin",)
            )

            admin_role = cursor.fetchone()

            if not admin_role:
                raise RuntimeError(
                    "Khong tim thay role admin. "
                    "Hay kiem tra database/schema.sql."
                )

            password_hash = generate_password_hash(password)

            cursor.execute(
                """
                INSERT INTO users (
                    full_name,
                    email,
                    password_hash,
                    role_id,
                    is_active
                )
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING id
                """,
                (
                    full_name,
                    email,
                    password_hash,
                    admin_role[0]
                )
            )

            admin_id = cursor.fetchone()[0]

        connection.commit()

        print("\nTao tai khoan Admin thanh cong!")
        print("Admin ID:", admin_id)
        print("Email:", email)
        print("Ban co the dang nhap tren website.")

    except Exception as error:
        if connection:
            connection.rollback()

        print("\nKhong the tao tai khoan Admin.")
        print("Chi tiet loi:", error)

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    main()
