#!/usr/bin/env python3
"""Generate test data for performance testing.

Usage:
    python3 seed_test_data.py [--customers 1000] [--meetings 10000] [--tasks 30000]

Generates:
    - N customers with random names and types
    - M meetings spread across customers
    - T tasks (some linked to meetings, some standalone)
    - Lightweight attachment metadata (no real files)
"""

import os
import sys
import random
import sqlite3
import uuid
import argparse
from datetime import datetime, timedelta, timezone

# Add parent dir to path so we can import from the app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Sample data ─────────────────────────────────────────────────
FIRST_NAMES = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
               "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗"]
LAST_NAMES = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军",
              "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀兰", "霞"]
CITIES = ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安", "重庆"]
INDUSTRIES = ["信息技术", "金融", "教育", "医疗", "制造", "零售", "物流", "房地产", "能源", "农业"]
REGIONS = ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]
TYPES = ["个人", "企业", "政府", "其他"]
PRIORITIES = ["normal", "important", "urgent"]
STATUSES = ["pending", "pending", "pending", "in_progress", "completed", "cancelled"]
MEETING_TEMPLATES = [
    "项目启动会议", "需求评审会议", "技术方案讨论", "项目进度同步",
    "问题复盘会", "季度汇报", "产品演示", "合同商谈",
    "客户回访", "技术支持沟通", "续约讨论", "预算审批",
]
TASK_TEMPLATES = [
    "整理需求文档", "跟进客户反馈", "安排技术评审", "编写测试用例",
    "更新项目计划", "联系供应商", "准备演示材料", "审核合同条款",
    "安排培训", "处理售后问题", "提交报销", "更新CRM数据",
    "发送周报", "确认会议时间", "回复客户邮件", "整理会议纪要",
]


def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)


def random_company():
    prefix = random.choice(["星辰", "华睿", "鼎新", "通达", "博雅", "恒远", "启明", "卓创"])
    suffix = random.choice(["科技", "信息", "集团", "控股", "咨询", "网络", "数据", "智能"])
    return prefix + suffix


def random_phone():
    return f"1{random.randint(30, 99):02d}{random.randint(10000000, 99999999)}"


def random_email(name):
    domains = ["qq.com", "163.com", "gmail.com", "example.com"]
    return f"{name.lower()}{random.randint(1, 999)}@{random.choice(domains)}"


def random_date(start_days=365, end_days=0):
    days_ago = random.randint(end_days, start_days)
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def random_datetime(start_days=365):
    days_ago = random.randint(0, start_days)
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=random.randint(0, 23))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def generate(db_path, num_customers=1000, num_meetings=10000, num_tasks=30000):
    """Generate test data in batches for performance."""
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("PRAGMA cache_size=-64000")

    now = now_utc()

    # ── Customers ─────────────────────────────────────────────
    print(f"Generating {num_customers} customers...")
    customer_ids = []
    for i in range(0, num_customers, 500):
        batch = []
        for j in range(i, min(i + 500, num_customers)):
            name = random_company()
            batch.append((
                str(uuid.uuid4()), name,
                random.choice(REGIONS),
                random.choice(TYPES),
                random_name(),
                random_name(),
                random_phone(),
                random_email(name[:3]),
                "",
                random.choice(CITIES),
                f"{random.choice(INDUSTRIES)}客户",
                random_datetime(365), now, None, "synced",
            ))
        db.executemany(
            """INSERT INTO customers (local_id, name, region, type, owner, contacts, phone, email,
               telegram, address, notes, created_at, updated_at, deleted_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        db.commit()
        print(f"  Customers: {min(i+500, num_customers)}/{num_customers}")

    rows = db.execute("SELECT id, local_id FROM customers").fetchall()
    customer_ids = rows
    print(f"  Done. {len(customer_ids)} customers.")

    # ── Meetings ───────────────────────────────────────────────
    print(f"Generating {num_meetings} meetings...")
    meeting_ids = []
    for i in range(0, num_meetings, 500):
        batch = []
        for j in range(i, min(i + 500, num_meetings)):
            c = random.choice(customer_ids)
            batch.append((
                str(uuid.uuid4()), c[0], c[1],
                random_date(730, 0),
                random.choice(MEETING_TEMPLATES),
                f"{random_name()}, {random_name()}",
                f"会议讨论了{random.choice(INDUSTRIES)}相关事项。决定下一步由{random_name()}负责推进。",
                random_datetime(365), now, None, "synced",
            ))
        db.executemany(
            """INSERT INTO meetings (local_id, customer_id, customer_local_id, meeting_date,
               title, participants, content, created_at, updated_at, deleted_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        db.commit()
        print(f"  Meetings: {min(i+500, num_meetings)}/{num_meetings}")

    rows = db.execute("SELECT id, local_id, customer_id FROM meetings").fetchall()
    meeting_ids = rows
    print(f"  Done. {len(meeting_ids)} meetings.")

    # ── Tasks ───────────────────────────────────────────────────
    print(f"Generating {num_tasks} tasks...")
    for i in range(0, num_tasks, 1000):
        batch = []
        for j in range(i, min(i + 1000, num_tasks)):
            c = random.choice(customer_ids)
            m = random.choice(meeting_ids) if random.random() < 0.8 else (None, None, None)
            status = random.choice(STATUSES)
            completed_at = now if status == "completed" else None
            has_due = random.random() < 0.6
            due_date = random_date(180, -30) if has_due else None
            batch.append((
                str(uuid.uuid4()), c[0], c[1],
                m[0] if m[0] else None, m[1] if m[1] else None,
                random.choice(TASK_TEMPLATES),
                random_name(),
                due_date,
                status,
                random.choice(PRIORITIES),
                f"备注：{random.randint(1, 999)}",
                random_datetime(365), now, completed_at, None, "synced",
            ))
        db.executemany(
            """INSERT INTO tasks (local_id, customer_id, customer_local_id, meeting_id, meeting_local_id,
               title, owner, due_date, status, priority, note, created_at, updated_at,
               completed_at, deleted_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        db.commit()
        print(f"  Tasks: {min(i+1000, num_tasks)}/{num_tasks}")

    print(f"  Done. {num_tasks} tasks.")

    # ── Attachments (lightweight metadata) ─────────────────────
    num_attachments = num_meetings // 3
    print(f"Generating {num_attachments} attachment records...")
    for i in range(0, num_attachments, 500):
        batch = []
        for j in range(i, min(i + 500, num_attachments)):
            m = random.choice(meeting_ids)
            cid = m[2] if len(m) > 2 else 1
            ext = random.choice(["pdf", "docx", "xlsx", "png", "jpg"])
            fname = f"document_{random.randint(1, 99999)}.{ext}"
            batch.append((
                str(uuid.uuid4()), cid, "", m[0], m[1],
                fname, f"uploads/{fname}", f"application/{ext}", random.randint(1024, 5242880),
                random_datetime(365), now, None, "synced",
            ))
        db.executemany(
            """INSERT INTO attachments (local_id, customer_id, customer_local_id, meeting_id, meeting_local_id,
               filename, file_path, mime_type, file_size, created_at, updated_at, deleted_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        db.commit()
        print(f"  Attachments: {min(i+500, num_attachments)}/{num_attachments}")

    print(f"  Done. {num_attachments} attachments.")

    # ── Create admin user ───────────────────────────────────────
    from werkzeug.security import generate_password_hash
    existing = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin")),
        )
        db.commit()
        print("Created admin user (admin/admin).")

    db.close()
    print("\n=== Seed complete! ===")
    print(f"  Customers:    {num_customers}")
    print(f"  Meetings:     {num_meetings}")
    print(f"  Tasks:        {num_tasks}")
    print(f"  Attachments:  {num_attachments}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CRM test data.")
    parser.add_argument("--customers", type=int, default=1000)
    parser.add_argument("--meetings", type=int, default=10000)
    parser.add_argument("--tasks", type=int, default=30000)
    parser.add_argument("--db", type=str, default="data.db")
    args = parser.parse_args()

    if os.path.exists(args.db):
        print(f"WARNING: {args.db} already exists. Delete it first? [y/N] ", end="")
        if input().strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)
        os.remove(args.db)

    # Ensure schema exists
    from db import init_db
    from flask import Flask
    import config
    app = Flask(__name__)
    app.config.from_object(config)
    init_db(app)

    generate(args.db, args.customers, args.meetings, args.tasks)
