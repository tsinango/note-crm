"""
CRM — Flask application.
Customer meeting notes & task management.
"""
import os
import csv
import io
import uuid
import zipfile
import functools
import time
from datetime import datetime, timezone, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, session, g,
)
from werkzeug.utils import secure_filename

from config import DATABASE, UPLOAD_FOLDER, MAX_CONTENT_LENGTH, SECRET_KEY
from db import (
    init_db, get_db, close_db, query_one, query_all, execute,
    soft_delete, now_utc, new_local_id,
)
from auth import auth_bp, login_required, get_current_user, ensure_admin_exists

# ── Allowed upload extensions ────────────────────────────────────
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "csv", "zip", "rar", "7z",
}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── CSRF helper ──────────────────────────────────────────────────
def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = uuid.uuid4().hex
    return session["_csrf_token"]

def check_csrf():
    """Validate CSRF token for POST/PUT/DELETE requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    # Exempt login, setup, and sync API endpoints from CSRF
    if request.endpoint in ("auth.login_page", "auth.setup_page"):
        return True
    if request.path.startswith("/api/sync/"):
        return True
    token = request.form.get("_csrf_token", "")
    expected = session.get("_csrf_token", "")
    return token and token == expected

# ── Rate limiter for login ───────────────────────────────────────
LOGIN_ATTEMPTS = {}  # ip -> (count, window_start)

def check_login_rate(ip, max_attempts=10, window_sec=300):
    """Return True if login is allowed, False if rate-limited."""
    now = time.time()
    entry = LOGIN_ATTEMPTS.get(ip)
    if entry is None or now - entry[1] > window_sec:
        LOGIN_ATTEMPTS[ip] = (1, now)
        return True
    count, start = entry
    if count >= max_attempts:
        return False
    LOGIN_ATTEMPTS[ip] = (count + 1, start)
    return True


def create_app():
    app = Flask(__name__)

    # Require SECRET_KEY in production
    if SECRET_KEY and SECRET_KEY != "change-me-in-production-please":
        app.config["SECRET_KEY"] = SECRET_KEY
    else:
        key = os.environ.get("SECRET_KEY", "")
        if not key and not app.debug:
            raise RuntimeError(
                "SECRET_KEY must be set via environment variable. "
                "Set export SECRET_KEY=<random-string> before starting."
            )
        app.config["SECRET_KEY"] = key or "dev-secret-key-change-in-production"

    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.teardown_appcontext(close_db)

    # Inject CSRF token and user into all templates
    @app.context_processor
    def inject_globals():
        return {
            "csrf_token": generate_csrf_token(),
            "current_user": get_current_user(),
            "page_url": _make_page_url,
        }

    def _make_page_url(page_num):
        args = dict(request.args)
        args["page"] = str(page_num)
        qs = "&".join(f"{k}={v}" for k, v in args.items())
        return f"{request.path}?{qs}" if qs else request.path

    # CSRF check before every request
    @app.before_request
    def csrf_protect():
        if not check_csrf():
            flash("CSRF 验证失败，请刷新页面后重试", "danger")
            return redirect(request.referrer or url_for("index"))

    app.register_blueprint(auth_bp)

    # ── Init DB on first access ──────────────────────────────────
    with app.app_context():
        if not os.path.exists(DATABASE):
            init_db(app)
            ensure_admin_exists(app)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    #  INDEX
    # ═══════════════════════════════════════════════════════════

    @app.route("/")
    @login_required
    def index():
        return redirect(url_for("customers"))

    # ═══════════════════════════════════════════════════════════
    #  CUSTOMERS (with pagination)
    # ═══════════════════════════════════════════════════════════

    @app.route("/customers")
    @login_required
    def customers():
        search = request.args.get("q", "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(200, int(request.args.get("page_size", 50))))
        offset = (page - 1) * page_size

        where = "c.deleted_at IS NULL"
        params = []

        if search:
            like = f"%{search}%"
            where += " AND (c.name LIKE ? OR c.notes LIKE ? OR c.contacts LIKE ?)"
            params.extend([like, like, like])

        # Count total
        total_row = query_one(
            f"SELECT COUNT(*) as total FROM customers c WHERE {where}", tuple(params)
        )
        total = total_row["total"] if total_row else 0

        # Fetch page
        rows = query_all(
            f"""SELECT c.*,
                (SELECT MAX(meeting_date) FROM meetings
                 WHERE customer_id=c.id AND deleted_at IS NULL) as last_meeting,
                (SELECT COUNT(*) FROM tasks
                 WHERE customer_id=c.id
                   AND status IN ('pending','in_progress')
                   AND deleted_at IS NULL) as pending_count
            FROM customers c
            WHERE {where}
            ORDER BY c.updated_at DESC
            LIMIT ? OFFSET ?""",
            tuple(params) + (page_size, offset),
        )

        total_pages = max(1, (total + page_size - 1) // page_size)

        return render_template(
            "customers.html",
            customers=rows,
            search=search,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )

    @app.route("/customers/new", methods=["POST"])
    @login_required
    def customer_create():
        name = request.form.get("name", "").strip()
        if not name:
            flash("客户名称不能为空", "danger")
            return redirect(url_for("customers"))

        local_id = request.form.get("local_id", "") or new_local_id()
        cid = execute(
            """INSERT INTO customers
               (local_id, name, type, owner, contacts, phone, email,
                telegram, address, notes, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                local_id,
                name,
                request.form.get("type", "").strip(),
                request.form.get("owner", "").strip(),
                request.form.get("contacts", "").strip(),
                request.form.get("phone", "").strip(),
                request.form.get("email", "").strip(),
                request.form.get("telegram", "").strip(),
                request.form.get("address", "").strip(),
                request.form.get("notes", "").strip(),
                "synced",
            ),
        )
        # Return the created ID for offline sync
        if request.headers.get("X-Client-Local-Id"):
            return jsonify({"local_id": local_id, "id": cid})
        flash("客户已添加", "success")
        return redirect(url_for("customers"))

    @app.route("/customers/<int:cid>/edit", methods=["POST"])
    @login_required
    def customer_edit(cid):
        name = request.form.get("name", "").strip()
        if not name:
            flash("客户名称不能为空", "danger")
            return redirect(url_for("customer_detail", cid=cid))

        execute(
            """UPDATE customers SET name=?, type=?, owner=?, contacts=?,
               phone=?, email=?, telegram=?, address=?, notes=?,
               updated_at=?, sync_status='pending_update'
               WHERE id=? AND deleted_at IS NULL""",
            (
                name,
                request.form.get("type", "").strip(),
                request.form.get("owner", "").strip(),
                request.form.get("contacts", "").strip(),
                request.form.get("phone", "").strip(),
                request.form.get("email", "").strip(),
                request.form.get("telegram", "").strip(),
                request.form.get("address", "").strip(),
                request.form.get("notes", "").strip(),
                now_utc(),
                cid,
            ),
        )
        flash("客户信息已更新", "success")
        return redirect(url_for("customer_detail", cid=cid))

    @app.route("/customers/<int:cid>/delete", methods=["POST"])
    @login_required
    def customer_delete(cid):
        soft_delete("customers", cid)
        flash("客户已删除", "info")
        return redirect(url_for("customers"))

    # ═══════════════════════════════════════════════════════════
    #  CUSTOMER DETAIL (batched queries — no N+1)
    # ═══════════════════════════════════════════════════════════

    MEETINGS_PER_PAGE = 20

    @app.route("/customers/<int:cid>")
    @login_required
    def customer_detail(cid):
        customer = query_one(
            "SELECT * FROM customers WHERE id=? AND deleted_at IS NULL", (cid,)
        )
        if not customer:
            flash("客户不存在", "danger")
            return redirect(url_for("customers"))

        # 1) All tasks for this customer (one query)
        customer_tasks = query_all(
            """SELECT t.*, m.title as meeting_title
               FROM tasks t
               LEFT JOIN meetings m ON t.meeting_id = m.id AND m.deleted_at IS NULL
               WHERE t.customer_id=? AND t.deleted_at IS NULL
               ORDER BY
                 CASE t.status
                   WHEN 'pending' THEN 0
                   WHEN 'in_progress' THEN 1
                   WHEN 'completed' THEN 2
                   WHEN 'cancelled' THEN 3
                 END,
                 CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
                 t.due_date ASC""",
            (cid,),
        )

        # 2) Most recent 20 meetings (one query)
        meetings = query_all(
            """SELECT * FROM meetings
               WHERE customer_id=? AND deleted_at IS NULL
               ORDER BY meeting_date DESC, created_at DESC
               LIMIT ?""",
            (cid, MEETINGS_PER_PAGE),
        )

        # Total meeting count for "load more"
        total_meetings_row = query_one(
            """SELECT COUNT(*) as total FROM meetings
               WHERE customer_id=? AND deleted_at IS NULL""",
            (cid,),
        )
        total_meetings = total_meetings_row["total"] if total_meetings_row else 0

        # 3) All tasks & attachments for these meeting_ids (one query each)
        meeting_ids = [m["id"] for m in meetings]
        meeting_tasks = {}
        all_attachments = []
        if meeting_ids:
            placeholders = ",".join(["?"] * len(meeting_ids))
            task_rows = query_all(
                f"""SELECT * FROM tasks
                    WHERE meeting_id IN ({placeholders}) AND deleted_at IS NULL
                    ORDER BY
                      CASE status
                        WHEN 'pending' THEN 0
                        WHEN 'in_progress' THEN 1
                        WHEN 'completed' THEN 2
                        WHEN 'cancelled' THEN 3
                      END,
                      due_date ASC""",
                meeting_ids,
            )
            for t in task_rows:
                meeting_tasks.setdefault(t["meeting_id"], []).append(t)

            attach_rows = query_all(
                f"""SELECT * FROM attachments
                    WHERE meeting_id IN ({placeholders}) AND deleted_at IS NULL
                    ORDER BY created_at DESC""",
                meeting_ids,
            )
            all_attachments = attach_rows

        # Summary
        pending_tasks = [
            t for t in customer_tasks
            if t["status"] in ("pending", "in_progress")
        ]

        now = datetime.now(timezone.utc)

        return render_template(
            "customer_detail.html",
            customer=customer,
            pending_tasks=pending_tasks,
            meetings=meetings,
            meeting_tasks=meeting_tasks,
            attachments=all_attachments,
            total_meetings=total_meetings,
            now=now,
        )

    # ── Load more meetings (AJAX) ───────────────────────────────
    @app.route("/api/customers/<int:cid>/meetings")
    @login_required
    def api_customer_meetings(cid):
        limit = min(100, int(request.args.get("limit", 20)))
        offset = max(0, int(request.args.get("offset", 0)))

        meetings = query_all(
            """SELECT * FROM meetings
               WHERE customer_id=? AND deleted_at IS NULL
               ORDER BY meeting_date DESC, created_at DESC
               LIMIT ? OFFSET ?""",
            (cid, limit, offset),
        )

        total_row = query_one(
            "SELECT COUNT(*) as total FROM meetings WHERE customer_id=? AND deleted_at IS NULL",
            (cid,),
        )
        total = total_row["total"] if total_row else 0

        # Batch tasks and attachments
        meeting_ids = [m["id"] for m in meetings]
        tasks_by_meeting = {}
        attachments_list = []
        if meeting_ids:
            placeholders = ",".join(["?"] * len(meeting_ids))
            task_rows = query_all(
                f"""SELECT * FROM tasks
                    WHERE meeting_id IN ({placeholders}) AND deleted_at IS NULL
                    ORDER BY due_date ASC""",
                meeting_ids,
            )
            for t in task_rows:
                tasks_by_meeting.setdefault(t["meeting_id"], []).append(t)

            attach_rows = query_all(
                f"""SELECT * FROM attachments
                    WHERE meeting_id IN ({placeholders}) AND deleted_at IS NULL
                    ORDER BY created_at DESC""",
                meeting_ids,
            )
            attachments_list = attach_rows

        return jsonify({
            "meetings": meetings,
            "tasks": tasks_by_meeting,
            "attachments": attachments_list,
            "total": total,
            "has_more": (offset + limit) < total,
        })

    # ═══════════════════════════════════════════════════════════
    #  MEETINGS
    # ═══════════════════════════════════════════════════════════

    @app.route("/customers/<int:cid>/meetings/new", methods=["POST"])
    @login_required
    def meeting_create(cid):
        title = request.form.get("title", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip()
        if not title or not meeting_date:
            flash("会议标题和日期不能为空", "danger")
            return redirect(url_for("customer_detail", cid=cid))

        local_id = request.form.get("local_id", "") or new_local_id()
        mid = execute(
            """INSERT INTO meetings
               (local_id, customer_id, customer_local_id,
                meeting_date, title, participants, content, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                local_id,
                cid,
                request.form.get("customer_local_id", ""),
                meeting_date,
                title,
                request.form.get("participants", "").strip(),
                request.form.get("content", "").strip(),
                "synced",
            ),
        )
        if request.headers.get("X-Client-Local-Id"):
            return jsonify({"local_id": local_id, "id": mid})
        flash("会议纪要已添加", "success")
        return redirect(url_for("customer_detail", cid=cid))

    @app.route("/meetings/<int:mid>/edit", methods=["POST"])
    @login_required
    def meeting_edit(mid):
        meeting = query_one(
            "SELECT * FROM meetings WHERE id=? AND deleted_at IS NULL", (mid,)
        )
        if not meeting:
            flash("会议不存在", "danger")
            return redirect(url_for("customers"))

        title = request.form.get("title", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip()
        if not title or not meeting_date:
            flash("会议标题和日期不能为空", "danger")
            return redirect(url_for("customer_detail", cid=meeting["customer_id"]))

        execute(
            """UPDATE meetings SET title=?, meeting_date=?, participants=?,
               content=?, updated_at=?, sync_status='pending_update'
               WHERE id=? AND deleted_at IS NULL""",
            (
                title, meeting_date,
                request.form.get("participants", "").strip(),
                request.form.get("content", "").strip(),
                now_utc(), mid,
            ),
        )
        flash("会议纪要已更新", "success")
        return redirect(url_for("customer_detail", cid=meeting["customer_id"]))

    @app.route("/meetings/<int:mid>/delete", methods=["POST"])
    @login_required
    def meeting_delete(mid):
        meeting = query_one(
            "SELECT * FROM meetings WHERE id=? AND deleted_at IS NULL", (mid,)
        )
        if meeting:
            soft_delete("meetings", mid)
            flash("会议纪要已删除", "info")
            return redirect(url_for("customer_detail", cid=meeting["customer_id"]))
        flash("会议不存在", "danger")
        return redirect(url_for("customers"))

    # ═══════════════════════════════════════════════════════════
    #  TASKS (with pagination)
    # ═══════════════════════════════════════════════════════════

    @app.route("/tasks")
    @login_required
    def tasks():
        status_filter = request.args.get("status", "").strip()
        priority_filter = request.args.get("priority", "").strip()
        owner_filter = request.args.get("owner", "").strip()
        customer_filter = request.args.get("customer_id", "").strip()
        due_filter = request.args.get("due", "").strip()
        search = request.args.get("q", "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(500, int(request.args.get("page_size", 100))))
        offset = (page - 1) * page_size

        conditions = ["t.deleted_at IS NULL", "c.deleted_at IS NULL"]
        params = []

        if status_filter and status_filter != "all":
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            placeholders = ",".join(["?"] * len(statuses))
            conditions.append(f"t.status IN ({placeholders})")
            params.extend(statuses)
        elif not status_filter:
            conditions.append("t.status IN ('pending', 'in_progress')")

        if priority_filter:
            conditions.append("t.priority = ?")
            params.append(priority_filter)

        if owner_filter:
            conditions.append("t.owner LIKE ?")
            params.append(f"%{owner_filter}%")

        if customer_filter:
            conditions.append("t.customer_id = ?")
            params.append(int(customer_filter))

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if due_filter == "overdue":
            conditions.append("t.due_date < ?")
            params.append(today_str)
        elif due_filter == "today":
            conditions.append("t.due_date = ?")
            params.append(today_str)
        elif due_filter == "week":
            week_end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
            conditions.append("t.due_date BETWEEN ? AND ?")
            params.extend([today_str, week_end])
        elif due_filter in ("no_due", "nodue"):
            conditions.append("(t.due_date IS NULL OR t.due_date = '')")

        if search:
            like = f"%{search}%"
            conditions.append("(t.title LIKE ? OR t.owner LIKE ? OR t.note LIKE ?)")
            params.extend([like, like, like])

        where = " AND ".join(conditions)
        param_tuple = tuple(params)

        # Count
        total_row = query_one(
            f"""SELECT COUNT(*) as total
                FROM tasks t JOIN customers c ON t.customer_id = c.id
                WHERE {where}""",
            param_tuple,
        )
        total = total_row["total"] if total_row else 0

        # Fetch page (only essential columns — no meeting content/customer notes)
        tasks_list = query_all(
            f"""SELECT t.id, t.title, t.owner, t.due_date, t.status, t.priority,
                       t.note, t.customer_id, t.meeting_id,
                       c.name as customer_name,
                       m.title as meeting_title
                FROM tasks t
                JOIN customers c ON t.customer_id = c.id
                LEFT JOIN meetings m ON t.meeting_id = m.id AND m.deleted_at IS NULL
                WHERE {where}
                ORDER BY
                  CASE WHEN t.due_date IS NULL OR t.due_date = '' THEN 1 ELSE 0 END,
                  t.due_date ASC,
                  CASE t.priority
                    WHEN 'urgent' THEN 0
                    WHEN 'important' THEN 1
                    ELSE 2
                  END
                LIMIT ? OFFSET ?""",
            param_tuple + (page_size, offset),
        )

        total_pages = max(1, (total + page_size - 1) // page_size)

        all_customers = query_all(
            "SELECT id, name FROM customers WHERE deleted_at IS NULL ORDER BY name"
        )

        return render_template(
            "tasks.html",
            tasks=tasks_list,
            all_customers=all_customers,
            today=today_str,
            current_status=status_filter or "pending,in_progress",
            current_priority=priority_filter or "",
            current_due=due_filter or "",
            current_customer_id=customer_filter or "",
            current_owner=owner_filter or "",
            search=search,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )

    @app.route("/tasks/new", methods=["POST"])
    @login_required
    def task_create():
        cid = request.form.get("customer_id", "")
        mid = request.form.get("meeting_id", "") or None
        title = request.form.get("title", "").strip()
        if not title:
            flash("待办内容不能为空", "danger")
            return redirect_back(cid)

        local_id = request.form.get("local_id", "") or new_local_id()
        tid = execute(
            """INSERT INTO tasks
               (local_id, customer_id, customer_local_id,
                meeting_id, meeting_local_id,
                title, owner, due_date, status, priority, note, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                local_id,
                int(cid) if cid else None,
                request.form.get("customer_local_id", ""),
                int(mid) if mid else None,
                request.form.get("meeting_local_id", ""),
                title,
                request.form.get("owner", "").strip(),
                request.form.get("due_date", "").strip() or None,
                request.form.get("status", "pending"),
                request.form.get("priority", "normal"),
                request.form.get("note", "").strip(),
                "synced",
            ),
        )
        if request.headers.get("X-Client-Local-Id"):
            return jsonify({"local_id": local_id, "id": tid})
        flash("待办事项已添加", "success")
        return redirect_back(cid)

    @app.route("/tasks/<int:tid>/edit", methods=["POST"])
    @login_required
    def task_edit(tid):
        task = query_one(
            "SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)
        )
        if not task:
            flash("待办不存在", "danger")
            return redirect(url_for("tasks"))

        new_status = request.form.get("status", task["status"])
        execute(
            """UPDATE tasks SET title=?, owner=?, due_date=?, status=?,
               priority=?, note=?, updated_at=?, completed_at=?,
               sync_status='pending_update'
               WHERE id=? AND deleted_at IS NULL""",
            (
                request.form.get("title", "").strip(),
                request.form.get("owner", "").strip(),
                request.form.get("due_date", "").strip() or None,
                new_status,
                request.form.get("priority", "normal"),
                request.form.get("note", "").strip(),
                now_utc(),
                now_utc() if new_status == "completed" else task["completed_at"],
                tid,
            ),
        )
        flash("待办事项已更新", "success")
        return redirect_back(task["customer_id"])

    @app.route("/tasks/<int:tid>/toggle", methods=["POST"])
    @login_required
    def task_toggle(tid):
        task = query_one(
            "SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)
        )
        if not task:
            flash("待办不存在", "danger")
            return redirect(url_for("tasks"))

        new_status = "completed" if task["status"] != "completed" else "pending"
        execute(
            """UPDATE tasks SET status=?, updated_at=?, completed_at=?,
               sync_status='pending_update' WHERE id=?""",
            (
                new_status, now_utc(),
                now_utc() if new_status == "completed" else None,
                tid,
            ),
        )
        flash("待办状态已更新", "success")
        return redirect_back(task["customer_id"])

    @app.route("/tasks/<int:tid>/delete", methods=["POST"])
    @login_required
    def task_delete(tid):
        task = query_one(
            "SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)
        )
        if task:
            soft_delete("tasks", tid)
            flash("待办已删除", "info")
            return redirect_back(task["customer_id"])
        flash("待办不存在", "danger")
        return redirect(url_for("tasks"))

    @app.route("/tasks/quick-status", methods=["POST"])
    @login_required
    def task_quick_status():
        tid = request.form.get("id", "")
        new_status = request.form.get("status", "")
        return_url = request.form.get("return_url", url_for("tasks"))
        if not tid or not new_status:
            flash("参数错误", "danger")
            return redirect(return_url)

        task = query_one(
            "SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (int(tid),)
        )
        if not task:
            flash("待办不存在", "danger")
            return redirect(return_url)

        execute(
            """UPDATE tasks SET status=?, updated_at=?, completed_at=?,
               sync_status='pending_update' WHERE id=?""",
            (
                new_status, now_utc(),
                now_utc() if new_status == "completed" else None,
                int(tid),
            ),
        )
        flash("待办状态已更新", "success")
        return redirect(return_url)

    # ═══════════════════════════════════════════════════════════
    #  ATTACHMENTS
    # ═══════════════════════════════════════════════════════════

    @app.route("/attachments/upload", methods=["POST"])
    @login_required
    def attachment_upload():
        cid = request.form.get("customer_id", "")
        mid = request.form.get("meeting_id", "")
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("请选择文件", "danger")
            return redirect_back(cid)

        filename = file.filename
        if not allowed_file(filename):
            flash("不支持的文件类型", "danger")
            return redirect_back(cid)

        safe_name = secure_filename(filename)
        # Prepend timestamp to avoid collisions
        ts = now_utc().replace(" ", "_").replace(":", "-")
        safe_name = f"{ts}_{safe_name}"
        file_path = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(file_path)

        execute(
            """INSERT INTO attachments
               (local_id, customer_id, customer_local_id,
                meeting_id, meeting_local_id,
                filename, file_path, mime_type, file_size, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_local_id(),
                int(cid) if cid else None,
                request.form.get("customer_local_id", ""),
                int(mid) if mid else None,
                request.form.get("meeting_local_id", ""),
                filename,
                safe_name,
                file.content_type or "",
                os.path.getsize(file_path),
                "synced",
            ),
        )
        flash("附件已上传", "success")
        return redirect_back(cid)

    @app.route("/attachments/<int:aid>")
    @login_required
    def attachment_download(aid):
        att = query_one(
            "SELECT * FROM attachments WHERE id=? AND deleted_at IS NULL", (aid,)
        )
        if not att:
            flash("附件不存在", "danger")
            return redirect(url_for("customers"))
        fp = os.path.join(UPLOAD_FOLDER, att["file_path"])
        if not os.path.exists(fp):
            flash("文件不存在", "danger")
            return redirect_back(att.get("customer_id") or "")
        return send_file(fp, download_name=att["filename"], mimetype=att["mime_type"])

    @app.route("/attachments/<int:aid>/delete", methods=["POST"])
    @login_required
    def attachment_delete(aid):
        att = query_one(
            "SELECT * FROM attachments WHERE id=? AND deleted_at IS NULL", (aid,)
        )
        if att:
            soft_delete("attachments", aid)
            flash("附件已删除", "info")
            return redirect_back(att.get("customer_id") or "")
        flash("附件不存在", "danger")
        return redirect(url_for("customers"))

    # ═══════════════════════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════════════════════

    @app.route("/search")
    @login_required
    def search():
        q = request.args.get("q", "").strip()
        if not q:
            return render_template("search.html", query="", results={})
        results = search_query(q)
        return render_template("search.html", query=q, results=results)

    # ═══════════════════════════════════════════════════════════
    #  BACKUP / EXPORT
    # ═══════════════════════════════════════════════════════════

    @app.route("/export/csv")
    @login_required
    def export_csv():
        entity = request.args.get("type", "customers")
        if entity not in ("customers", "meetings", "tasks"):
            flash("无效的导出类型", "danger")
            return redirect(url_for("customers"))

        rows = query_all(
            f"SELECT * FROM {entity} WHERE deleted_at IS NULL ORDER BY id"
        )
        if not rows:
            flash("没有数据可导出", "info")
            return redirect(url_for("customers"))

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

        buf = io.BytesIO()
        buf.write(output.getvalue().encode("utf-8-sig"))
        buf.seek(0)
        return send_file(
            buf, mimetype="text/csv",
            as_attachment=True, download_name=f"{entity}.csv"
        )

    @app.route("/export/backup")
    @login_required
    def export_backup():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            db_path = DATABASE
            if os.path.exists(db_path):
                zf.write(db_path, "data.db")
            upload_dir = UPLOAD_FOLDER
            if os.path.exists(upload_dir):
                for root, dirs, files in os.walk(upload_dir):
                    for fn in files:
                        if fn == ".gitkeep":
                            continue
                        fp = os.path.join(root, fn)
                        zf.write(fp, os.path.join("uploads", fn))
        buf.seek(0)
        return send_file(
            buf, mimetype="application/zip",
            as_attachment=True, download_name="crm_backup.zip"
        )

    # ═══════════════════════════════════════════════════════════
    #  SYNC API
    # ═══════════════════════════════════════════════════════════

    @app.route("/api/sync/bootstrap")
    @login_required
    def sync_bootstrap():
        scope = request.args.get("scope", "initial")
        limit = min(1000, int(request.args.get("limit", 500)))
        cursor = request.args.get("cursor", "")

        if scope == "initial":
            # Lightweight: only essential data
            customers = query_all(
                "SELECT id, local_id, name, type, owner FROM customers WHERE deleted_at IS NULL"
            )
            tasks = query_all(
                """SELECT * FROM tasks
                   WHERE deleted_at IS NULL AND status IN ('pending','in_progress')"""
            )
            ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
            meetings = query_all(
                """SELECT * FROM meetings
                   WHERE deleted_at IS NULL AND meeting_date >= ?
                   ORDER BY meeting_date DESC""",
                (ninety_days_ago,),
            )
            attachments = query_all(
                "SELECT id, local_id, meeting_id, filename, mime_type, file_size FROM attachments WHERE deleted_at IS NULL"
            )
            return jsonify({
                "customers": customers,
                "meetings": meetings,
                "tasks": tasks,
                "attachments": attachments,
            })

        # Full with cursor pagination
        if cursor:
            customers = query_all(
                "SELECT * FROM customers WHERE deleted_at IS NULL AND id > ? ORDER BY id LIMIT ?",
                (int(cursor), limit),
            )
        else:
            customers = query_all(
                "SELECT * FROM customers WHERE deleted_at IS NULL ORDER BY id LIMIT ?",
                (limit,),
            )

        meetings = query_all(
            """SELECT * FROM meetings
               WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
        tasks = query_all(
            """SELECT * FROM tasks
               WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
        attachments = query_all(
            "SELECT * FROM attachments WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        )

        has_more = len(customers) >= limit
        next_cursor = str(customers[-1]["id"]) if has_more and customers else None

        return jsonify({
            "customers": customers,
            "meetings": meetings,
            "tasks": tasks,
            "attachments": attachments,
            "has_more": has_more,
            "next_cursor": next_cursor,
        })

    @app.route("/api/sync/push", methods=["POST"])
    @login_required
    def sync_push():
        data = request.get_json(silent=True) or {}
        id_map = {
            "customers": [],
            "meetings": [],
            "tasks": [],
        }
        errors = []

        for table in ("customers", "meetings", "tasks"):
            for item in data.get(table, []):
                local_id = item.get("local_id")
                try:
                    result = _apply_push_item(table, item)
                    if result.get("local_id"):
                        id_map[table].append(result)
                except Exception as e:
                    errors.append({"local_id": local_id, "error": str(e)})

        return jsonify({"id_map": id_map, "errors": errors})

    @app.route("/api/sync/pull")
    @login_required
    def sync_pull():
        since = request.args.get("since", "1970-01-01 00:00:00")
        limit = min(1000, int(request.args.get("limit", 500)))
        cursor = request.args.get("cursor", "")

        def _pull_table(table, id_col="id"):
            cond = f"updated_at > ?"
            params = [since]
            if cursor:
                cond += f" AND {id_col} > ?"
                params.append(int(cursor))
            rows = query_all(
                f"SELECT * FROM {table} WHERE {cond} ORDER BY {id_col} LIMIT ?",
                tuple(params) + (limit,),
            )
            has_more = len(rows) >= limit
            next_c = str(rows[-1][id_col]) if has_more and rows else None
            return rows, has_more, next_c

        customers, cm, cc = _pull_table("customers")
        meetings, mm, mc = _pull_table("meetings")
        tasks, tm, tc = _pull_table("tasks")
        attachments, am, ac = _pull_table("attachments")

        return jsonify({
            "customers": customers,
            "meetings": meetings,
            "tasks": tasks,
            "attachments": attachments,
            "server_time": now_utc(),
            "has_more": cm or mm or tm or am,
            "next_cursor": cc or mc or tc or ac,
        })

    # ── Sync helpers ────────────────────────────────────────────

    def _apply_push_item(table, item):
        local_id = item.get("local_id")
        status = item.get("sync_status")

        if status == "pending_create":
            existing = query_one(
                f"SELECT id FROM {table} WHERE local_id=?", (local_id,)
            )
            if existing:
                _update_item(table, existing["id"], item)
                return {"local_id": local_id, "id": existing["id"]}
            else:
                cols = []
                vals = []
                for k, v in item.items():
                    if k not in ("id", "sync_status"):
                        cols.append(k)
                        vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                new_id = execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                    tuple(vals),
                )
                return {"local_id": local_id, "id": new_id}

        elif status == "pending_update":
            existing = query_one(
                f"SELECT id FROM {table} WHERE local_id=?", (local_id,)
            )
            if existing:
                _update_item(table, existing["id"], item)
                return {"local_id": local_id, "id": existing["id"]}

        elif status == "pending_delete":
            existing = query_one(
                f"SELECT id FROM {table} WHERE local_id=? AND deleted_at IS NULL",
                (local_id,),
            )
            if existing:
                soft_delete(table, existing["id"])
                return {"local_id": local_id, "id": existing["id"]}

        return {}

    def _update_item(table, record_id, item):
        sets = []
        vals = []
        for k, v in item.items():
            if k not in ("id", "local_id", "sync_status", "created_at"):
                sets.append(f"{k}=?")
                vals.append(v)
        sets.append("sync_status='synced'")
        vals.append(record_id)
        execute(
            f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", tuple(vals)
        )

    # ── Shared redirect helper ──────────────────────────────────

    def redirect_back(cid):
        if cid:
            return redirect(url_for("customer_detail", cid=cid))
        ref = request.form.get("_redirect") or request.args.get("_redirect", "")
        if ref == "tasks":
            return redirect(url_for("tasks"))
        return redirect(url_for("customers"))

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
