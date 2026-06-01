# CRM — 客户会议纪要与待办事项管理

自用轻量级 Web App。客户管理、会议纪要、待办追踪。

## 快速开始

```bash
cd crm
pip install flask werkzeug

# 设置密钥和管理员（首次启动）
export SECRET_KEY="your-random-secret-here"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="your-password"

python3 app.py
# → http://localhost:5000
```

或者访问 `/setup` 页面交互式创建管理员（当没有用户时）。

## 生产部署 (Linux VPS)

```bash
pip install gunicorn
export SECRET_KEY="random-string"
gunicorn wsgi:app -b 0.0.0.0:8000 -w 2
```

配合 Nginx 反向代理，见 README 旧版中的 systemd/nginx 配置。

## 安全

- 生产环境 **必须** 设置 `SECRET_KEY` 环境变量，否则无法启动。
- 没有默认密码，通过 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 或 `/setup` 页面创建管理员。
- 所有 POST 表单有 CSRF 保护。
- 上传文件限制白名单扩展名，使用 `secure_filename`。
- 登录有速率限制（5 次/5 分钟/IP）。
- 附件下载要求登录。

## 生成测试数据

```bash
python3 seed_test_data.py --customers 1000 --meetings 10000 --tasks 30000
```

## 备份

```bash
# CSV 导出（浏览器访问）
http://localhost:5000/export/csv?type=customers
http://localhost:5000/export/csv?type=meetings
http://localhost:5000/export/csv?type=tasks

# 完整备份 zip（含数据库 + 上传文件）
http://localhost:5000/export/backup
```

## 离线使用

1. 首次在线访问后 PWA Service Worker 缓存核心资源。
2. 离线时 JS 表单拦截，数据写入 IndexedDB（pending_create/pending_update）。
3. 重新联网后 **先推后拉**：先 push 本地 pending 到后端，再 pull 服务器更新做 merge。
4. 有 pending 数据时 pull 不做 clearStore，只做 upsert。
5. 离线 badge 明确显示离线状态。

## 目录

```
crm/
├── app.py                 # Flask 主应用
├── auth.py                # 认证（速率限制、管理员创建）
├── config.py              # 配置
├── db.py                  # 数据库工具
├── wsgi.py                # Gunicorn 入口
├── seed_test_data.py      # 测试数据生成
├── run_dev.sh             # 开发启动脚本
├── requirements.txt
├── migrations/001_init.sql
├── templates/             # Jinja2 模板
└── static/                # CSS, JS, PWA, Service Worker
```
