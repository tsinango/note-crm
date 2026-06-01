"""Simple session-based authentication."""
from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, query_one, execute

auth_bp = Blueprint("auth", __name__)


def login_required(view):
    """Decorator: redirect to login if not authenticated."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)

    return wrapped


def get_current_user():
    """Return current user dict or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    return query_one("SELECT id, username FROM users WHERE id = ?", (uid,))


def seed_default_user():
    """Create a default user if none exists."""
    existing = query_one("SELECT id FROM users LIMIT 1")
    if existing is None:
        pw_hash = generate_password_hash("admin")
        execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", pw_hash))


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE username = ?", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("登录成功", "success")
            return redirect(url_for("customers"))
        flash("用户名或密码错误", "danger")
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("auth.login_page"))
