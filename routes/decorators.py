
from functools import wraps
from flask import session, redirect, url_for, flash, abort


def role_required(*allowed_roles):
    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if not session.get("user_id"):
                flash("Vui lòng đăng nhập để tiếp tục.", "error")
                return redirect(url_for("auth.login"))
            current_role = session.get("role")

            print("========== KIEM TRA QUYEN ==========")
            print("USER ID:", session.get("user_id"))
            print("CURRENT ROLE:", repr(current_role))
            print("ALLOWED ROLES:", repr(allowed_roles))
            print("====================================")

            if current_role not in allowed_roles:
                abort(403)

            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator
