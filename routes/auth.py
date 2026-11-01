
import re
from flask import current_app
import psycopg2
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from psycopg2.extras import RealDictCursor
from flask_wtf.csrf import generate_csrf


auth_bp = Blueprint("auth", __name__)


def valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not email or not password:
            flash("Vui lòng nhập đầy đủ thông tin.", "error")
            return render_template("register.html")

        if len(full_name) > 150:
            flash("Họ tên không được vượt quá 150 ký tự.", "error")
            return render_template("register.html")

        if not valid_email(email):
            flash("Địa chỉ email không hợp lệ.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Mật khẩu phải có ít nhất 8 ký tự.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Mật khẩu xác nhận không khớp.", "error")
            return render_template("register.html")

        from config.database import get_connection

        connection = None

        try:
            connection = get_connection()

            with connection.cursor(cursor_factory=RealDictCursor) as cursor:

                # Kiểm tra email đã tồn tại chưa
                cursor.execute(
                    "SELECT id FROM users WHERE email = %s",
                    (email,)
                )

                if cursor.fetchone():
                    flash("Email này đã được đăng ký.", "error")
                    return render_template("register.html")

                # Chỉ cho phép đăng ký tài khoản Student
                cursor.execute(
                    "SELECT id FROM roles WHERE role_name = %s",
                    ("student",)
                )

                student_role = cursor.fetchone()

                if not student_role:
                    raise RuntimeError(
                        "Chưa tìm thấy vai trò student trong database."
                    )

                # Mã hóa mật khẩu
                password_hash = generate_password_hash(password)

                cursor.execute(
                    """
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role_id
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        full_name,
                        email,
                        password_hash,
                        student_role["id"]
                    )
                )

                new_user = cursor.fetchone()
                connection.commit()

            flash(
                "Đăng ký thành công! Hãy đăng nhập để tiếp tục.",
                "success"
            )

            return redirect(url_for("auth.login"))

        except psycopg2.IntegrityError:
            if connection:
                connection.rollback()

            flash("Email đã tồn tại hoặc dữ liệu không hợp lệ.", "error")

        except Exception:
            if connection:
                connection.rollback()

            current_app.logger.exception("Registration failed")
            flash("Không thể đăng ký lúc này. Vui lòng thử lại.", "error")

        finally:
            if connection:
                connection.close()

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Vui lòng nhập email và mật khẩu.", "error")
            return render_template("login.html")

        from config.database import get_connection

        connection = None

        try:
            connection = get_connection()

            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        users.id,
                        users.full_name,
                        users.email,
                        users.password_hash,
                        roles.role_name
                    FROM users
                    JOIN roles ON users.role_id = roles.id
                    WHERE users.email = %s
                      AND users.is_active = TRUE
                    """,
                    (email,)
                )

                user = cursor.fetchone()

            if user and check_password_hash(
                user["password_hash"],
                password
            ):
                session.clear()

                session["user_id"] = user["id"]
                session["full_name"] = user["full_name"]
                session["email"] = user["email"]
                session["role"] = user["role_name"]
                current_app.logger.warning(
                    "LOGIN USER ID: %r | EMAIL: %r | ROLE: %r",
                    session.get("user_id"),
                    session.get("email"),
                    session.get("role")
                )
                flash(
                    "Đăng nhập thành công!",
                    "success"
                )

                return redirect(url_for("dashboard"))

            flash("Email hoặc mật khẩu không chính xác.", "error")

        except Exception:
            current_app.logger.exception("Login failed")
            flash("Không thể đăng nhập lúc này. Vui lòng thử lại.", "error")

        finally:
            if connection:
                connection.close()

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()

    flash("Bạn đã đăng xuất thành công.", "success")

    return redirect(url_for("index"))
