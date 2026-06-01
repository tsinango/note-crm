"""Simple session-based authentication with rate limiting."""
import os
import time
from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, query_one, execute
import threading

auth_bp = Blueprint("auth", __name__)

# ── Rate limiting (in-process, per-IP) ────────────────────────
_login_attempts = {}
_lock = threading.Lock()
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 300  # 5 minutes


def _check_rate_limit(ip):
    now = time.time()
    with _lock:
        attempts = _login_attempts.get(ip, [])
        # Purge old entries
        attempts = [t for t in attempts if now - t < ATTEMPT_WINDOW]
        _login_attempts[ip] = attempts
        if len(attempts) >= MAX_ATTEMPTS:
            return False
        attempts.append(now)
        return True


# ── Decorator ─────────────────────────────────────────────────
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)
    return wrapped


def get_current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return query_one("SELECT id, username FROM users WHERE id = ?", (uid,))


def ensure_admin_exists(app):
    """Create admin user from env vars or interactive prompt. No default password."""
    existing = query_one("SELECT id FROM users LIMIT 1")
    if existing:
        return  # already has users

    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if username and password:
        pw_hash = generate_password_hash(password)
        execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        app.logger.info(f"Admin user '{username}' created from environment variables.")
        return

    # No env vars — print instructions and exit if in production style
    if not app.debug and os.environ.get("SECRET_KEY", "change-me") == "change-me-in-production-please":
        app.logger.warning(
            "No admin user exists and ADMIN_USERNAME/ADMIN_PASSWORD not set. "
            "The first user to access /setup will be able to create an admin account."
        )


# ── Routes ─────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        ip = request.remote_addr or "127.0.0.1"

        if not _check_rate_limit(ip):
            flash("登录尝试过于频繁，请 5 分钟后再试", "danger")
            return render_template("login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE username = ?", (username,))

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["_csrf_token"] = os.urandom(32).hex()
            flash("登录成功", "success")
            return redirect(url_for("customers"))

        flash("用户名或密码错误", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup_page():
    """First-time admin creation when no users exist."""
    existing = query_one("SELECT id FROM users LIMIT 1")
    if existing:
        flash("系统已初始化", "info")
        return redirect(url_for("auth.login_page"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not username or len(username) < 2:
            flash("用户名至少 2 个字符", "danger")
        elif len(password) < 6:
            flash("密码至少 6 个字符", "danger")
        elif password != password2:
            flash("两次密码不一致", "danger")
        else:
            pw_hash = generate_password_hash(password)
            execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )
            flash("管理员账号创建成功，请登录", "success")
            return redirect(url_for("auth.login_page"))

    return render_template("setup.html")
