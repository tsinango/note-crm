"""Database helpers — init, get_db, query wrappers."""
import sqlite3
import uuid
from datetime import datetime, timezone
from flask import g
from config import DATABASE


def get_db():
    """Get a database connection for the current request."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(exception=None):
    """Close the database connection at the end of a request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables from the migration SQL file."""
    import os
    sql_path = os.path.join(app.root_path, "migrations", "001_init.sql")
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys=ON")
    with open(sql_path) as f:
        db.executescript(f.read())
    db.commit()
    db.close()
    # Apply any schema migrations for existing databases
    migrate_schema(DATABASE)


def migrate_schema(db_path):
    """Apply ALTER TABLE migrations that don't break existing data."""
    import sqlite3
    try:
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA foreign_keys=ON")
        # Add region column if not present
        try:
            db.execute("ALTER TABLE customers ADD COLUMN region TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        db.commit()
        db.close()
    except Exception:
        pass  # ignore migration errors on old/new databases


def new_local_id():
    return str(uuid.uuid4())


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows):
    """Convert a list of sqlite3.Row to a list of dicts."""
    return [dict(r) for r in rows]


def query_one(sql, params=()):
    """Return a single row as dict, or None."""
    row = get_db().execute(sql, params).fetchone()
    return row_to_dict(row)


def query_all(sql, params=()):
    """Return all rows as list of dicts."""
    return rows_to_dicts(get_db().execute(sql, params).fetchall())


def execute(sql, params=()):
    """Execute a write statement; return lastrowid."""
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


def soft_delete(table, record_id):
    """Mark a record as deleted by setting deleted_at."""
    execute(
        f"UPDATE {table} SET deleted_at = ?, updated_at = ?, sync_status = 'pending_update' WHERE id = ? AND deleted_at IS NULL",
        (now_utc(), now_utc(), record_id),
    )


def search_query(term):
    """Search across customers, meetings, and tasks. Returns dict of lists."""
    like = f"%{term}%"
    customers = query_all(
        """SELECT id, name, type, owner, phone, email,
                  (SELECT MAX(meeting_date) FROM meetings WHERE customer_id = customers.id AND deleted_at IS NULL) as last_meeting,
                  (SELECT COUNT(*) FROM tasks WHERE customer_id = customers.id AND status IN ('pending','in_progress') AND deleted_at IS NULL) as pending_tasks
           FROM customers
           WHERE deleted_at IS NULL
             AND (name LIKE ? OR notes LIKE ? OR contacts LIKE ? OR phone LIKE ? OR email LIKE ?)
           ORDER BY name""",
        (like, like, like, like, like),
    )
    meetings = query_all(
        """SELECT m.id, m.title, m.meeting_date, m.participants, m.customer_id, c.name as customer_name
           FROM meetings m JOIN customers c ON m.customer_id = c.id
           WHERE m.deleted_at IS NULL AND c.deleted_at IS NULL
             AND (m.title LIKE ? OR m.content LIKE ? OR m.participants LIKE ?)
           ORDER BY m.meeting_date DESC LIMIT 50""",
        (like, like, like),
    )
    tasks = query_all(
        """SELECT t.id, t.title, t.status, t.priority, t.due_date, t.owner, t.customer_id, c.name as customer_name
           FROM tasks t JOIN customers c ON t.customer_id = c.id
           WHERE t.deleted_at IS NULL AND c.deleted_at IS NULL
             AND (t.title LIKE ? OR t.owner LIKE ? OR t.note LIKE ?)
           ORDER BY t.due_date ASC LIMIT 50""",
        (like, like, like),
    )
    return {"customers": customers, "meetings": meetings, "tasks": tasks}
