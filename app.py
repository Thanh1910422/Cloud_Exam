
import os
from flask import (
    Flask,
    render_template,
    jsonify,
    session,
    redirect,
    url_for
)
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

from routes.auth import auth_bp
from routes.admin import admin_bp


load_dotenv()

app = Flask(__name__)

secret_key = os.getenv("SECRET_KEY")

if not secret_key:
    raise RuntimeError("Chưa cấu hình SECRET_KEY trong file .env")

app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("VERCEL") == "1"
)

# Bật bảo vệ CSRF
csrf = CSRFProtect(app)

# Đăng ký nhóm đường dẫn đăng nhập, đăng ký, đăng xuất
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        from flask import flash
        flash("Vui lòng đăng nhập để tiếp tục.", "error")
        return redirect(url_for("auth.login"))

    role = session.get("role")

    dashboard_templates = {
        "admin": "admin/dashboard.html",
        "teacher": "teacher/dashboard.html",
        "student": "student/dashboard.html"
    }

    template = dashboard_templates.get(role)

    if not template:
        session.clear()
        flash("Vai trò tài khoản không hợp lệ. Vui lòng đăng nhập lại.", "error")
        return redirect(url_for("auth.login"))

    return render_template(template)


@app.route("/health")
def health():
    return jsonify({
        "status": "success",
        "application": "HSK Exam",
        "message": "HSK Exam is running"
    })


@app.route("/health/database")
def database_health():
    from config.database import get_connection

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        return jsonify({
            "status": "success",
            "database": "connected"
        })

    except Exception:
        app.logger.exception("Database connection failed")

        return jsonify({
            "status": "error",
            "database": "disconnected"
        }), 503

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
