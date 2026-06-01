#!/bin/sh
export SECRET_KEY=test-dev-key-2024
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin123
exec python3 app.py
