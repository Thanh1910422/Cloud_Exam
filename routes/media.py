import time

from flask import Blueprint, abort, redirect, session, current_app


media_bp = Blueprint("media", __name__)

LINK_SECONDS = 60 * 60          # link tạm sống 1 giờ
CACHE_SECONDS = 50 * 60         # dùng lại link trong 50 phút
ALLOWED_PREFIX = "exams/"
ALLOWED_FOLDER = "/question_images/"

_cache = {}


@media_bp.route("/media/<path:storage_path>")
def question_media(storage_path):
    if not session.get("user_id"):
        abort(401)

    # Chỉ cho xem ảnh câu hỏi, không cho tải file đề / đáp án gốc
    if (
        not storage_path.startswith(ALLOWED_PREFIX)
        or ALLOWED_FOLDER not in storage_path
        or ".." in storage_path
    ):
        abort(404)

    cached = _cache.get(storage_path)
    if cached and cached[1] > time.time():
        return redirect(cached[0])

    try:
        from config.storage import storage

        result = storage.create_signed_url(storage_path, LINK_SECONDS)
        url = result.get("signedURL") or result.get("signedUrl")
    except Exception:
        current_app.logger.exception("Cannot sign media url")
        url = None

    if not url:
        abort(404)

    _cache[storage_path] = (url, time.time() + CACHE_SECONDS)
    response = redirect(url)
    response.headers["Cache-Control"] = "private, max-age=600"
    return response
