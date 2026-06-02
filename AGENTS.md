# Repository Guidelines

## Project Structure & Module Organization

This repository contains a lightweight Flask meeting memo and to-do utility for customer records, meeting notes, tasks, uploads, and offline/PWA use.

- `app.py` is the main Flask application and route layer.
- `auth.py`, `config.py`, and `db.py` hold authentication, configuration, and database helpers.
- `wsgi.py` is the Gunicorn entry point for production.
- `migrations/` contains SQL schema migrations, currently starting with `001_init.sql`.
- `templates/` contains Jinja2 templates; keep page-specific markup there.
- `static/` contains CSS, JavaScript, PWA files, and service worker assets.
- `uploads/` stores user-uploaded files and should not be treated as source code.
- `seed_test_data.py` creates local-only sample data.

## Build, Test, and Development Commands

Set up dependencies in a virtual environment when possible:

```bash
pip install -r requirements.txt
```

Run the app locally:

```bash
export SECRET_KEY="dev-secret"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="change-me"
python3 app.py
```

On Windows PowerShell, use `$env:SECRET_KEY="dev-secret"` style environment variables. The app serves at `http://localhost:5000` by default. For production-like execution, run:

```bash
gunicorn wsgi:app -b 0.0.0.0:8000 -w 2
```

Generate large local test data only outside production:

```bash
python3 seed_test_data.py --customers 1000 --meetings 10000 --tasks 30000
```

## Coding Style & Naming Conventions

Use Python 3 conventions with 4-space indentation, `snake_case` for functions and variables, and concise route/helper names that match the domain. Keep Flask route handlers readable; move reusable database, auth, or configuration logic into helper modules. For templates, prefer clear Jinja block names and keep JavaScript in `static/` unless the script is tightly coupled to one template.

## Testing Guidelines

There is no dedicated test framework configured yet. Before submitting changes, run at least:

```bash
python3 -m py_compile app.py auth.py config.py db.py wsgi.py seed_test_data.py
```

For UI, auth, upload, export, and offline/PWA changes, manually verify the affected browser workflow. If adding tests, use `pytest`, place tests under `tests/`, and name files `test_*.py`.

## Commit & Pull Request Guidelines

Recent commits use short, imperative messages such as `Fix draft clear execution order` and `Add Bootswatch theme preview`. Follow that style: start with an action verb, keep the subject specific, and avoid unrelated changes in the same commit.

Pull requests should include a brief summary, manual test notes or command output, linked issue/context when available, and screenshots for visible UI changes. Call out any database migration, security, upload, or service worker behavior changes explicitly.

## Security & Configuration Tips

Production must set `SECRET_KEY`; do not commit real secrets, databases, backups, or uploaded customer files. Admin credentials should come from environment variables or the `/setup` flow. Treat `seed_test_data.py` credentials and generated data as local development only.
