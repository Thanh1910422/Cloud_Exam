"""
Thống kê:
    /admin/stats?period=30         Admin: tài khoản đăng ký, giảng viên, kết quả thi
    /teacher/results?period=30     Giáo viên: kết quả thi các đề mình phụ trách
period = 7 | 30 | 90 | all
"""

from flask import (
    Blueprint,
    render_template,
    current_app,
    flash,
    redirect,
    url_for,
    session,
    request
)
from psycopg2.extras import RealDictCursor

from config.database import get_connection
from routes.decorators import role_required
from services import statistics as stats


statistics_bp = Blueprint("statistics", __name__)


@statistics_bp.route("/admin/stats")
@role_required("admin")
def admin_stats():
    period, days = stats.parse_period(request.args.get("period"))
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            data = {
                "accounts": stats.account_summary(cursor, days),
                "exam_counts": stats.exam_summary(cursor),
                "results": stats.result_summary(cursor, days),
                "registrations": stats.registrations_by_day(cursor, days),
                "recent_accounts": stats.recent_accounts(cursor),
                "teachers": stats.teacher_stats(cursor, days),
                "exams": stats.exam_stats(cursor, days),
                "distribution": stats.score_distribution(cursor, days),
                "hardest": stats.hardest_questions(cursor, days),
            }

        return render_template(
            "admin/stats.html",
            period=period,
            periods=stats.PERIOD_CHOICES,
            **data
        )

    except Exception:
        current_app.logger.exception("Cannot load admin statistics")
        flash("Không thể tải thống kê.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()


@statistics_bp.route("/teacher/results")
@role_required("teacher")
def teacher_results():
    period, days = stats.parse_period(request.args.get("period"))
    teacher_id = session.get("user_id")
    connection = None

    try:
        connection = get_connection()

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            data = {
                "exam_counts": stats.exam_summary(cursor, teacher_id),
                "results": stats.result_summary(cursor, days, teacher_id),
                "exams": stats.exam_stats(cursor, days, teacher_id),
                "distribution": stats.score_distribution(cursor, days, teacher_id),
                "hardest": stats.hardest_questions(cursor, days, teacher_id),
            }

        return render_template(
            "teacher/results.html",
            period=period,
            periods=stats.PERIOD_CHOICES,
            **data
        )

    except Exception:
        current_app.logger.exception("Cannot load teacher results")
        flash("Không thể tải kết quả thi.", "error")
        return redirect(url_for("dashboard"))

    finally:
        if connection:
            connection.close()
