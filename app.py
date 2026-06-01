"""Main Flask application — all routes for customers, meetings, tasks, search."""
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from datetime import datetime, timezone, timedelta
from config import SECRET_KEY, UPLOAD_FOLDER, MAX_CONTENT_LENGTH
from db import (
    init_db, get_db, close_db, query_one, query_all, execute,
    soft_delete, search_query, now_utc, new_local_id,
)
from auth import auth_bp, login_required, seed_default_user, get_current_user
import csv
import io
import zipfile


def create_app():
    app = Flask(__name__)
    app.config.from_object("config")
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)

    # ── Init DB on first request ─────────────────────────────────
    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            init_db(app)
        seed_default_user()
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    #  CUSTOMERS
    # ═══════════════════════════════════════════════════════════

    @app.route("/")
    @login_required
    def index():
        return redirect(url_for("customers"))

    @app.route("/customers")
    @login_required
    def customers():
        search = request.args.get("q", "").strip()
        if search:
            like = f"%{search}%"
            rows = query_all(
                """SELECT c.*,
                   (SELECT MAX(meeting_date) FROM meetings WHERE customer_id=c.id AND deleted_at IS NULL) as last_meeting,
                   (SELECT COUNT(*) FROM tasks WHERE customer_id=c.id AND status IN ('pending','in_progress') AND deleted_at IS NULL) as pending_count
                FROM customers c
                WHERE c.deleted_at IS NULL AND (c.name LIKE ? OR c.notes LIKE ? OR c.contacts LIKE ?)
                ORDER BY c.name""",
                (like, like, like),
            )
        else:
            rows = query_all(
                """SELECT c.*,
                   (SELECT MAX(meeting_date) FROM meetings WHERE customer_id=c.id AND deleted_at IS NULL) as last_meeting,
                   (SELECT COUNT(*) FROM tasks WHERE customer_id=c.id AND status IN ('pending','in_progress') AND deleted_at IS NULL) as pending_count
                FROM customers c
                WHERE c.deleted_at IS NULL
                ORDER BY c.updated_at DESC""",
            )
        return render_template("customers.html", customers=rows, search=search)

    @app.route("/customers/new", methods=["POST"])
    @login_required
    def customer_create():
        name = request.form.get("name", "").strip()
        if not name:
            flash("客户名称不能为空", "danger")
            return redirect(url_for("customers"))

        data = {
            "local_id": new_local_id(),
            "name": name,
            "type": request.form.get("type", "").strip(),
            "owner": request.form.get("owner", "").strip(),
            "contacts": request.form.get("contacts", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "email": request.form.get("email", "").strip(),
            "telegram": request.form.get("telegram", "").strip(),
            "address": request.form.get("address", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "sync_status": "synced",
        }
        execute(
            """INSERT INTO customers (local_id, name, type, owner, contacts, phone, email, telegram, address, notes, sync_status)
               VALUES (:local_id, :name, :type, :owner, :contacts, :phone, :email, :telegram, :address, :notes, :sync_status)""",
            data,
        )
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
            """UPDATE customers SET name=?, type=?, owner=?, contacts=?, phone=?, email=?,
               telegram=?, address=?, notes=?, updated_at=?, sync_status='pending_update'
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
    #  CUSTOMER DETAIL (meetings + tasks)
    # ═══════════════════════════════════════════════════════════

    @app.route("/customers/<int:cid>")
    @login_required
    def customer_detail(cid):
        customer = query_one("SELECT * FROM customers WHERE id=? AND deleted_at IS NULL", (cid,))
        if not customer:
            flash("客户不存在", "danger")
            return redirect(url_for("customers"))

        # Pending & in-progress tasks for this customer
        customer_tasks = query_all(
            """SELECT t.*, m.title as meeting_title, m.meeting_date as meeting_date
               FROM tasks t
               LEFT JOIN meetings m ON t.meeting_id = m.id AND m.deleted_at IS NULL
               WHERE t.customer_id=? AND t.deleted_at IS NULL
               ORDER BY
                 CASE t.status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'completed' THEN 2 WHEN 'cancelled' THEN 3 END,
                 CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
                 t.due_date ASC""",
            (cid,),
        )

        # Meetings for this customer, newest first
        meetings = query_all(
            """SELECT * FROM meetings
               WHERE customer_id=? AND deleted_at IS NULL
               ORDER BY meeting_date DESC, created_at DESC""",
            (cid,),
        )

        # Tasks grouped by meeting
        meeting_tasks = {}
        for m in meetings:
            meeting_tasks[m["id"]] = query_all(
                """SELECT * FROM tasks
                   WHERE meeting_id=? AND deleted_at IS NULL
                   ORDER BY
                     CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'completed' THEN 2 WHEN 'cancelled' THEN 3 END,
                     due_date ASC""",
                (m["id"],),
            )

        # Attachments for each meeting
        meeting_attachments = {}
        for m in meetings:
            meeting_attachments[m["id"]] = query_all(
                """SELECT * FROM attachments
                   WHERE meeting_id=? AND deleted_at IS NULL
                   ORDER BY created_at DESC""",
                (m["id"],),
            )

        # Summary counts
        pending_tasks = [t for t in customer_tasks if t["status"] in ("pending", "in_progress")]
        pending_count = len(pending_tasks)
        completed_count = sum(1 for t in customer_tasks if t["status"] == "completed")

        # Flatten meeting tasks and attachments into single lists for template
        all_task_list = []
        for mt in meeting_tasks.values():
            all_task_list.extend(mt)
        all_att_list = []
        for ma in meeting_attachments.values():
            all_att_list.extend(ma)

        now = datetime.now(timezone.utc)

        return render_template(
            "customer_detail.html",
            customer=customer,
            pending_tasks=pending_tasks,
            all_tasks=all_task_list,
            attachments=all_att_list,
            meetings=meetings,
            meeting_tasks=meeting_tasks,
            meeting_attachments=meeting_attachments,
            pending_count=pending_count,
            completed_count=completed_count,
            now=now,
        )

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

        mid = execute(
            """INSERT INTO meetings (local_id, customer_id, customer_local_id, meeting_date, title, participants, content, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'synced')""",
            (
                new_local_id(),
                cid,
                request.form.get("customer_local_id", ""),
                meeting_date,
                title,
                request.form.get("participants", "").strip(),
                request.form.get("content", "").strip(),
            ),
        )
        flash("会议纪要已添加", "success")
        return redirect(url_for("customer_detail", cid=cid))

    @app.route("/meetings/<int:mid>/edit", methods=["POST"])
    @login_required
    def meeting_edit(mid):
        meeting = query_one("SELECT * FROM meetings WHERE id=? AND deleted_at IS NULL", (mid,))
        if not meeting:
            flash("会议不存在", "danger")
            return redirect(url_for("customers"))

        title = request.form.get("title", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip()
        if not title or not meeting_date:
            flash("会议标题和日期不能为空", "danger")
            return redirect(url_for("customer_detail", cid=meeting["customer_id"]))

        execute(
            """UPDATE meetings SET title=?, meeting_date=?, participants=?, content=?,
               updated_at=?, sync_status='pending_update'
               WHERE id=? AND deleted_at IS NULL""",
            (
                title,
                meeting_date,
                request.form.get("participants", "").strip(),
                request.form.get("content", "").strip(),
                now_utc(),
                mid,
            ),
        )
        flash("会议纪要已更新", "success")
        return redirect(url_for("customer_detail", cid=meeting["customer_id"]))

    @app.route("/meetings/<int:mid>/delete", methods=["POST"])
    @login_required
    def meeting_delete(mid):
        meeting = query_one("SELECT * FROM meetings WHERE id=? AND deleted_at IS NULL", (mid,))
        if meeting:
            soft_delete("meetings", mid)
            flash("会议纪要已删除", "info")
            return redirect(url_for("customer_detail", cid=meeting["customer_id"]))
        flash("会议不存在", "danger")
        return redirect(url_for("customers"))

    # ═══════════════════════════════════════════════════════════
    #  TASKS
    # ═══════════════════════════════════════════════════════════

    @app.route("/tasks")
    @login_required
    def tasks():
        # Filters
        status_filter = request.args.get("status", "").strip()
        priority_filter = request.args.get("priority", "").strip()
        owner_filter = request.args.get("owner", "").strip()
        customer_filter = request.args.get("customer_id", "").strip()
        due_filter = request.args.get("due", "").strip()  # overdue, today, week, no_due, all
        search = request.args.get("q", "").strip()

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

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if due_filter == "overdue":
            conditions.append("t.due_date < ?")
            params.append(today)
        elif due_filter == "today":
            conditions.append("t.due_date = ?")
            params.append(today)
        elif due_filter == "week":
            week_later = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
            conditions.append("t.due_date BETWEEN ? AND ?")
            params.append(today)
            params.append(week_later)
        elif due_filter in ("no_due", "nodue"):
            conditions.append("t.due_date IS NULL OR t.due_date = ''")

        if search:
            conditions.append("(t.title LIKE ? OR t.owner LIKE ? OR t.note LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where = " AND ".join(conditions)
        tasks_list = query_all(
            f"""SELECT t.*, c.name as customer_name,
                m.title as meeting_title, m.meeting_date as meeting_date
            FROM tasks t
            JOIN customers c ON t.customer_id = c.id
            LEFT JOIN meetings m ON t.meeting_id = m.id AND m.deleted_at IS NULL
            WHERE {where}
            ORDER BY
              CASE WHEN t.due_date IS NULL OR t.due_date = '' THEN 1 ELSE 0 END,
              t.due_date ASC,
              CASE t.priority WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END""",
            tuple(params),
        )

        # Get all customers for filter dropdown
        all_customers = query_all("SELECT id, name FROM customers WHERE deleted_at IS NULL ORDER BY name")

        return render_template(
            "tasks.html",
            tasks=tasks_list,
            all_customers=all_customers,
            today=today,
            current_status=status_filter or "pending,in_progress",
            current_priority=priority_filter or "",
            current_due=due_filter or "",
            current_customer_id=customer_filter or "",
            current_owner=owner_filter or "",
            search=search,
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

        execute(
            """INSERT INTO tasks (local_id, customer_id, customer_local_id, meeting_id, meeting_local_id,
               title, owner, due_date, status, priority, note, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced')""",
            (
                new_local_id(),
                int(cid),
                request.form.get("customer_local_id", ""),
                int(mid) if mid else None,
                request.form.get("meeting_local_id", ""),
                title,
                request.form.get("owner", "").strip(),
                request.form.get("due_date", "").strip() or None,
                request.form.get("status", "pending"),
                request.form.get("priority", "normal"),
                request.form.get("note", "").strip(),
            ),
        )
        flash("待办事项已添加", "success")
        return redirect_back(cid)

    @app.route("/tasks/<int:tid>/edit", methods=["POST"])
    @login_required
    def task_edit(tid):
        task = query_one("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,))
        if not task:
            flash("待办不存在", "danger")
            return redirect(url_for("tasks"))

        new_status = request.form.get("status", task["status"])
        execute(
            """UPDATE tasks SET title=?, owner=?, due_date=?, status=?, priority=?, note=?,
               updated_at=?, completed_at=?, sync_status='pending_update'
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
        task = query_one("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,))
        if not task:
            flash("待办不存在", "danger")
            return redirect(url_for("tasks"))

        new_status = "completed" if task["status"] != "completed" else "pending"
        execute(
            """UPDATE tasks SET status=?, updated_at=?, completed_at=?, sync_status='pending_update'
               WHERE id=?""",
            (new_status, now_utc(), now_utc() if new_status == "completed" else None, tid),
        )
        flash("待办状态已更新", "success")
        return redirect_back(task["customer_id"])

    @app.route("/tasks/<int:tid>/delete", methods=["POST"])
    @login_required
    def task_delete(tid):
        task = query_one("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,))
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

        task = query_one("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (int(tid),))
        if not task:
            flash("待办不存在", "danger")
            return redirect(return_url)

        execute(
            """UPDATE tasks SET status=?, updated_at=?, completed_at=?, sync_status='pending_update'
               WHERE id=?""",
            (new_status, now_utc(), now_utc() if new_status == "completed" else None, int(tid)),
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

        # Save file
        safe_name = f"{now_utc().replace(' ', '_').replace(':', '-')}_{file.filename}"
        file_path = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(file_path)

        execute(
            """INSERT INTO attachments (local_id, customer_id, customer_local_id, meeting_id, meeting_local_id,
               filename, file_path, mime_type, file_size, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced')""",
            (
                new_local_id(),
                int(cid) if cid else None,
                request.form.get("customer_local_id", ""),
                int(mid) if mid else None,
                request.form.get("meeting_local_id", ""),
                file.filename,
                safe_name,
                file.content_type or "",
                os.path.getsize(file_path),
            ),
        )
        flash("附件已上传", "success")
        return redirect_back(cid)

    @app.route("/attachments/<int:aid>")
    @login_required
    def attachment_download(aid):
        att = query_one("SELECT * FROM attachments WHERE id=? AND deleted_at IS NULL", (aid,))
        if not att:
            flash("附件不存在", "danger")
            return redirect(url_for("customers"))
        file_path = os.path.join(UPLOAD_FOLDER, att["file_path"])
        if not os.path.exists(file_path):
            flash("文件不存在", "danger")
            return redirect_back(att.get("customer_id", ""))
        return send_file(file_path, download_name=att["filename"], mimetype=att["mime_type"])

    @app.route("/attachments/<int:aid>/delete", methods=["POST"])
    @login_required
    def attachment_delete(aid):
        att = query_one("SELECT * FROM attachments WHERE id=? AND deleted_at IS NULL", (aid,))
        if att:
            soft_delete("attachments", aid)
            flash("附件已删除", "info")
            return redirect_back(att.get("customer_id", ""))
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

        rows = query_all(f"SELECT * FROM {entity} WHERE deleted_at IS NULL ORDER BY id")
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
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=f"{entity}.csv")

    @app.route("/export/backup")
    @login_required
    def export_backup():
        """Download a zip of the database and uploads folder."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add database
            db_path = app.config["DATABASE"]
            if os.path.exists(db_path):
                zf.write(db_path, "data.db")
            # Add uploads
            upload_dir = app.config["UPLOAD_FOLDER"]
            if os.path.exists(upload_dir):
                for root, dirs, files in os.walk(upload_dir):
                    for fn in files:
                        if fn == ".gitkeep":
                            continue
                        fp = os.path.join(root, fn)
                        zf.write(fp, os.path.join("uploads", fn))
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="crm_backup.zip")

    # ═══════════════════════════════════════════════════════════
    #  SYNC API (Phase 2 — stubs)
    # ═══════════════════════════════════════════════════════════

    @app.route("/api/sync/bootstrap")
    @login_required
    def sync_bootstrap():
        customers = query_all("SELECT * FROM customers WHERE deleted_at IS NULL")
        meetings = query_all("SELECT * FROM meetings WHERE deleted_at IS NULL")
        tasks = query_all("SELECT * FROM tasks WHERE deleted_at IS NULL")
        attachments = query_all("SELECT * FROM attachments WHERE deleted_at IS NULL")
        return jsonify({
            "customers": customers,
            "meetings": meetings,
            "tasks": tasks,
            "attachments": attachments,
        })

    @app.route("/api/sync/push", methods=["POST"])
    @login_required
    def sync_push():
        """Receive local changes from frontend and apply them."""
        data = request.get_json(silent=True) or {}
        results = {"created": 0, "updated": 0, "deleted": 0, "errors": []}

        for item in data.get("customers", []):
            try:
                _apply_push_item("customers", item)
                if item.get("sync_status") == "pending_create":
                    results["created"] += 1
                elif item.get("sync_status") == "pending_update":
                    results["updated"] += 1
                elif item.get("sync_status") == "pending_delete":
                    results["deleted"] += 1
            except Exception as e:
                results["errors"].append({"local_id": item.get("local_id"), "error": str(e)})

        for item in data.get("meetings", []):
            try:
                _apply_push_item("meetings", item)
                if item.get("sync_status") == "pending_create":
                    results["created"] += 1
                elif item.get("sync_status") == "pending_update":
                    results["updated"] += 1
                elif item.get("sync_status") == "pending_delete":
                    results["deleted"] += 1
            except Exception as e:
                results["errors"].append({"local_id": item.get("local_id"), "error": str(e)})

        for item in data.get("tasks", []):
            try:
                _apply_push_item("tasks", item)
                if item.get("sync_status") == "pending_create":
                    results["created"] += 1
                elif item.get("sync_status") == "pending_update":
                    results["updated"] += 1
                elif item.get("sync_status") == "pending_delete":
                    results["deleted"] += 1
            except Exception as e:
                results["errors"].append({"local_id": item.get("local_id"), "error": str(e)})

        return jsonify(results)

    @app.route("/api/sync/pull")
    @login_required
    def sync_pull():
        since = request.args.get("since", "1970-01-01 00:00:00")
        customers = query_all("SELECT * FROM customers WHERE updated_at > ?", (since,))
        meetings = query_all("SELECT * FROM meetings WHERE updated_at > ?", (since,))
        tasks = query_all("SELECT * FROM tasks WHERE updated_at > ?", (since,))
        attachments = query_all("SELECT * FROM attachments WHERE updated_at > ?", (since,))
        return jsonify({
            "customers": customers,
            "meetings": meetings,
            "tasks": tasks,
            "attachments": attachments,
            "server_time": now_utc(),
        })

    # ── Helper ──────────────────────────────────────────────────

    def _apply_push_item(table, item):
        local_id = item.get("local_id")
        status = item.get("sync_status")

        if status == "pending_create":
            # Insert — use local_id to avoid duplicates
            existing = query_one(f"SELECT id FROM {table} WHERE local_id=?", (local_id,))
            if existing:
                # Already exists, update instead
                _update_item(table, existing["id"], item)
            else:
                cols = []
                vals = []
                for k, v in item.items():
                    if k not in ("id", "sync_status"):
                        cols.append(k)
                        vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals)
                )

        elif status == "pending_update":
            existing = query_one(f"SELECT id FROM {table} WHERE local_id=?", (local_id,))
            if existing:
                _update_item(table, existing["id"], item)

        elif status == "pending_delete":
            existing = query_one(f"SELECT id FROM {table} WHERE local_id=? AND deleted_at IS NULL", (local_id,))
            if existing:
                soft_delete(table, existing["id"])

    def _update_item(table, record_id, item):
        sets = []
        vals = []
        for k, v in item.items():
            if k not in ("id", "local_id", "sync_status", "created_at"):
                sets.append(f"{k}=?")
                vals.append(v)
        sets.append("sync_status='synced'")
        vals.append(record_id)
        execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", tuple(vals))

    def redirect_back(cid):
        """Redirect to customer detail if cid, else tasks, else customers."""
        if cid:
            return redirect(url_for("customer_detail", cid=cid))
        ref = request.form.get("_redirect") or request.args.get("_redirect", "")
        if ref == "tasks":
            return redirect(url_for("tasks"))
        return redirect(url_for("customers"))

    return app


if __name__ == "__main__":
    import os
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
