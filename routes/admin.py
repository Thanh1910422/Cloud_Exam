
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app
)
from werkzeug.security import generate_password_hash
from psycopg2.extras import RealDictCursor

from config.database import get_connection
from routes.decorators import role_required


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@role_required("admin")
def dashboard():
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT r.role_name, COUNT(u.id) AS total
                FROM roles r
                LEFT JOIN users u ON u.role_id = r.id
                GROUP BY r.role_name
            """)

            role_counts = cursor.fetchall()

        return render_template(
            "admin/dashboard.html",
            role_counts=role_counts
        )

    except Exception:
        current_app.logger.exception("Cannot load admin dashboard")
        flash("Không thể tải dữ liệu quản trị.", "error")
        return render_template(
            "admin/dashboard.html",
            role_counts=[]
        )

    finally:
        if connection:
            connection.close()


@admin_bp.route("/teachers/new", methods=["GET", "POST"])
@role_required("admin")
def create_teacher():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not full_name or not email or not password:
            flash("Vui lòng nhập đầy đủ thông tin.", "error")
            return redirect(url_for("admin.create_teacher"))

        if len(password) < 8:
            flash("Mật khẩu phải có ít nhất 8 ký tự.", "error")
            return redirect(url_for("admin.create_teacher"))

        connection = None

        try:
            connection = get_connection()

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE email = %s",
                    (email,)
                )

                if cursor.fetchone():
                    flash("Email đã tồn tại.", "error")
                    return redirect(url_for("admin.create_teacher"))

                cursor.execute(
                    "SELECT id FROM roles WHERE role_name = %s",
                    ("teacher",)
                )

                teacher_role = cursor.fetchone()

                if not teacher_role:
                    raise RuntimeError("Không tìm thấy role teacher.")

                password_hash = generate_password_hash(password)

                cursor.execute("""
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash,
                        role_id,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, TRUE)
                """, (
                    full_name,
                    email,
                    password_hash,
                    teacher_role[0]
                ))

            connection.commit()

            flash("Tạo tài khoản giảng viên thành công.", "success")
            return redirect(url_for("admin.dashboard"))

        except Exception:
            if connection:
                connection.rollback()

            current_app.logger.exception("Cannot create teacher")
            flash("Không thể tạo tài khoản giảng viên.", "error")

        finally:
            if connection:
                connection.close()

    return render_template("admin/create_teacher.html")
