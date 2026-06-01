-- CRM Database Schema v1
-- Phase 1 MVP tables

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id TEXT UNIQUE,
    name TEXT NOT NULL,
    type TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    contacts TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    telegram TEXT DEFAULT '',
    address TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    sync_status TEXT DEFAULT 'synced'
);

CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id TEXT UNIQUE,
    customer_id INTEGER NOT NULL,
    customer_local_id TEXT,
    meeting_date TEXT NOT NULL,
    title TEXT DEFAULT '',
    participants TEXT DEFAULT '',
    content TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    sync_status TEXT DEFAULT 'synced',
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id TEXT UNIQUE,
    customer_id INTEGER NOT NULL,
    customer_local_id TEXT,
    meeting_id INTEGER,
    meeting_local_id TEXT,
    title TEXT NOT NULL,
    owner TEXT DEFAULT '',
    due_date TEXT,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'normal',
    note TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    deleted_at TIMESTAMP,
    sync_status TEXT DEFAULT 'synced',
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id TEXT UNIQUE,
    customer_id INTEGER,
    customer_local_id TEXT,
    meeting_id INTEGER,
    meeting_local_id TEXT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime_type TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    sync_status TEXT DEFAULT 'synced',
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE INDEX IF NOT EXISTS idx_meetings_customer ON meetings(customer_id, meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_deleted ON meetings(deleted_at);
CREATE INDEX IF NOT EXISTS idx_tasks_customer ON tasks(customer_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_meeting ON tasks(meeting_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner);
CREATE INDEX IF NOT EXISTS idx_tasks_deleted ON tasks(deleted_at);
CREATE INDEX IF NOT EXISTS idx_customers_deleted ON customers(deleted_at);
