"""Import legacy Obsidian customer notes into the CRM SQLite database.

The expected layout is:

    vintage/<region>/<customer>.md

Each Markdown file becomes one customer and one historical meeting. The file
modification time is used as the meeting date. Images and Obsidian wikilinks
are not imported specially; image embeds are removed and wikilink brackets are
converted to plain text by default.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def file_mtime_as_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def split_customer_name(file_stem: str) -> str:
    name = file_stem.strip()
    for separator in (" - ", " — ", " – "):
        if separator in name:
            name = name.rsplit(separator, 1)[-1].strip()
            break
    return name


def clean_markdown(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"!\[\[[^\]]+\]\]", stripped):
            continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", stripped):
            continue

        line = re.sub(r"!\[\[[^\]]+\]\]", "", line)
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", line)
        line = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", line)
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)
        lines.append(line.rstrip())

    return "\n".join(lines).strip()


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def ensure_schema(db: sqlite3.Connection, migration_path: Path) -> None:
    with migration_path.open("r", encoding="utf-8") as schema_file:
        db.executescript(schema_file.read())
    db.execute("PRAGMA foreign_keys=ON")


def import_file(db: sqlite3.Connection, md_path: Path, vintage_root: Path) -> tuple[bool, bool]:
    relative = md_path.relative_to(vintage_root)
    region = relative.parts[0] if len(relative.parts) > 1 else ""
    customer_name = split_customer_name(md_path.stem)
    source_key = relative.as_posix()
    customer_local_id = stable_id("vintage-customer", region, customer_name)
    meeting_local_id = stable_id("vintage-meeting", source_key)
    timestamp = now_utc()

    existing_customer = db.execute(
        "SELECT id FROM customers WHERE local_id = ? OR (name = ? AND region = ? AND deleted_at IS NULL)",
        (customer_local_id, customer_name, region),
    ).fetchone()

    customer_created = existing_customer is None
    if existing_customer is None:
        cursor = db.execute(
            """INSERT INTO customers
               (local_id, name, region, notes, created_at, updated_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, 'synced')""",
            (
                customer_local_id,
                customer_name,
                region,
                f"Imported from Obsidian: {source_key}",
                timestamp,
                timestamp,
            ),
        )
        customer_id = cursor.lastrowid
    else:
        customer_id = existing_customer["id"]

    existing_meeting = db.execute(
        "SELECT id FROM meetings WHERE local_id = ?",
        (meeting_local_id,),
    ).fetchone()
    meeting_created = existing_meeting is None
    if existing_meeting is None:
        content = clean_markdown(read_text(md_path))
        db.execute(
            """INSERT INTO meetings
               (local_id, customer_id, customer_local_id, meeting_date, title, content,
                created_at, updated_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synced')""",
            (
                meeting_local_id,
                customer_id,
                customer_local_id,
                file_mtime_as_date(md_path),
                "历史 Obsidian 笔记",
                content,
                timestamp,
                timestamp,
            ),
        )

    return customer_created, meeting_created


def import_vintage(db_path: Path, vintage_root: Path, dry_run: bool) -> tuple[int, int, int]:
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"
    files = sorted(vintage_root.rglob("*.md"))
    if dry_run:
        regions = sorted({path.relative_to(vintage_root).parts[0] for path in files if path.parts})
        print(f"DRY RUN: {len(files)} Markdown files found.")
        print(f"Regions: {', '.join(regions)}")
        return len(files), 0, 0

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        ensure_schema(db, migration_path)
        customer_count = 0
        meeting_count = 0
        for md_path in files:
            customer_created, meeting_created = import_file(db, md_path, vintage_root)
            customer_count += int(customer_created)
            meeting_count += int(meeting_created)
        db.commit()
        return len(files), customer_count, meeting_count
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import vintage Obsidian notes into data.db.")
    parser.add_argument("--vintage-root", default="vintage", help="Path to the vintage Obsidian folder.")
    parser.add_argument("--db", default="data.db", help="SQLite database path to import into.")
    parser.add_argument("--dry-run", action="store_true", help="Scan only; do not write to the database.")
    return parser.parse_args()


def main() -> None:
    configure_output_encoding()
    args = parse_args()
    vintage_root = Path(args.vintage_root).resolve()
    db_path = Path(args.db).resolve()
    if not vintage_root.exists():
        raise SystemExit(f"Vintage folder does not exist: {vintage_root}")

    scanned, customers, meetings = import_vintage(db_path, vintage_root, args.dry_run)
    if not args.dry_run:
        print(f"Scanned {scanned} Markdown files.")
        print(f"Created {customers} customers and {meetings} meetings.")
        print(f"Database: {db_path}")


if __name__ == "__main__":
    main()
