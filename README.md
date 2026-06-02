# meeting memo and to-do utility

A lightweight personal Flask web app for customer records, meeting memos, to-do tracking, file attachments, and offline-first use.

## Quick Start

```bash
cd note-crm
pip install -r requirements.txt

# Set the secret key and initial admin on first start
export SECRET_KEY="your-random-secret-here"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="your-password"

python3 app.py
# http://localhost:5000
```

You can also visit `/setup` to create the first admin account interactively when no users exist.

## Production Deployment

```bash
pip install gunicorn
export SECRET_KEY="random-string"
gunicorn wsgi:app -b 0.0.0.0:8000 -w 2
```

Use Nginx or another reverse proxy in front of Gunicorn for production deployments.

## Security

- Production must set `SECRET_KEY`; the app refuses to start without it.
- There is no built-in production password. Create the admin with `ADMIN_USERNAME` / `ADMIN_PASSWORD` or `/setup`.
- POST forms use CSRF protection.
- Uploads are restricted to an allowlist of file extensions and stored with `secure_filename`.
- Login attempts are rate-limited.
- Attachment downloads require authentication.

## Generate Test Data

> Local development only. Do not run this against production data.
> `seed_test_data.py` creates an `admin/admin` account and random sample records.

```bash
python3 seed_test_data.py --customers 1000 --meetings 10000 --tasks 30000
```

## Backup and Export

```text
# CSV exports in the browser
http://localhost:5000/export/csv?type=customers
http://localhost:5000/export/csv?type=meetings
http://localhost:5000/export/csv?type=tasks

# Full backup zip, including the database and uploaded files
http://localhost:5000/export/backup
```

## Offline Use

1. After the first online visit, the PWA service worker caches core assets.
2. When offline, form handlers save pending changes to IndexedDB.
3. When online again, sync pushes local pending changes first, then pulls server updates.
4. Pulls merge records instead of clearing local stores while pending local data exists.
5. The offline banner clearly shows offline status.

## Project Layout

```text
note-crm/
├── app.py                 # Main Flask app and routes
├── auth.py                # Authentication, rate limits, admin setup
├── config.py              # Runtime configuration
├── db.py                  # Database helpers
├── wsgi.py                # Gunicorn entry point
├── seed_test_data.py      # Local sample data generator
├── run_dev.sh             # Development launcher
├── requirements.txt
├── migrations/001_init.sql
├── templates/             # Jinja2 templates
└── static/                # CSS, JavaScript, PWA assets, service worker
```
