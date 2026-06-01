# CRM — 客户会议纪要与待办事项管理

一个自用的轻量级客户会议纪要和待办事项管理 Web App。

## 技术栈
- **后端**: Python 3 + Flask + SQLite
- **前端**: Jinja2 + Bootstrap 5 + 原生 JavaScript
- **离线**: PWA + Service Worker + IndexedDB
- **部署**: 可在 Linux VPS 上用 Gunicorn 运行

## 快速开始

```bash
# 1. 安装依赖
pip install flask werkzeug gunicorn

# 2. 启动开发服务器
cd crm
python3 app.py
# 访问 http://localhost:5010

# 3. 默认账号
# 用户名: admin / 密码: admin
# 首次启动会自动创建
```

## 生产部署 (Linux VPS)

```bash
# 安装
pip install flask werkzeug gunicorn
cd /opt/crm

# 设置环境变量
export SECRET_KEY="your-random-secret-key-here"

# 用 gunicorn 运行
gunicorn wsgi:app -b 0.0.0.0:8000 -w 2

# 或配合 systemd 服务
# 见下方 systemd 配置示例
```

### Systemd 服务文件 (`/etc/systemd/system/crm.service`)

```ini
[Unit]
Description=CRM Web App
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/crm
Environment=SECRET_KEY=your-random-secret
ExecStart=/usr/local/bin/gunicorn wsgi:app -b 127.0.0.1:8000 -w 2
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name crm.example.com;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 功能

### Phase 1 (已完成)
- 客户列表（搜索、新增、编辑、删除）
- 客户详情（信息编辑）
- 会议纪要时间线（新增、编辑、删除）
- 客户页面待办汇总卡片
- 全局待办页面（按状态/DDL/优先级/客户/责任人筛选）
- 全文搜索
- 简单登录
- PC + 手机浏览器适配

### Phase 2 (已完成)
- PWA: manifest + Service Worker 离线缓存
- IndexedDB 本地数据库
- 离线查看已缓存数据
- 同步 API: bootstrap / push / pull

### Phase 3 (已完成)
- 附件上传（图片、PDF 等）
- 备份 zip 下载（数据库 + 上传文件）
- CSV 导出（客户/会议/待办）

## 数据库

SQLite 单文件 `data.db`，所有表使用软删除（deleted_at）。包含：

| 表 | 说明 |
|---|---|
| customers | 客户表 |
| meetings | 会议纪要表 |
| tasks | 待办事项表 |
| attachments | 附件表 |
| users | 用户表 |

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/sync/bootstrap | 同步引导（返回全量数据） |
| POST | /api/sync/push | 推送本地变更 |
| GET | /api/sync/pull?since= | 拉取增量更新 |
| POST | /attachments/upload | 上传附件 |
| GET | /attachments/<id> | 下载附件 |
| GET | /export/csv?type=customers | CSV 导出 |
| GET | /export/backup | 备份 zip 下载 |

## 数据备份

- 页面右上角用户菜单 → "备份下载" → 下载 zip（含数据库和上传文件）
- `/export/csv?type=customers` → 导出客户 CSV
- `/export/csv?type=meetings` → 导出会议 CSV
- `/export/csv?type=tasks` → 导出待办 CSV

## 修改密码

首次启动后默认密码为 `admin`。通过 SQLite 修改：

```bash
python3 -c "
from werkzeug.security import generate_password_hash
print(generate_password_hash('your-new-password'))
"
# 将输出的哈希值更新到 users 表
sqlite3 data.db \"UPDATE users SET password_hash='<hash>' WHERE username='admin'\"
```

## 离线使用

1. 首次在线访问后，Service Worker 会缓存核心页面和资源
2. 离线时可以查看已缓存的数据（通过 IndexedDB 同步过的）
3. 离线时创建/编辑的数据会在 IndexedDB 中标记为 pending
4. 重新联网后自动推送到后端

## 目录结构

```
crm/
├── app.py                 # Flask 应用主文件
├── auth.py                # 登录认证
├── config.py              # 配置
├── db.py                  # 数据库工具
├── wsgi.py                # Gunicorn 入口
├── requirements.txt       # Python 依赖
├── data.db                # SQLite 数据库（自动创建）
├── uploads/               # 上传文件目录
├── migrations/
│   └── 001_init.sql       # 数据库建表脚本
├── templates/
│   ├── base.html          # 基础布局
│   ├── login.html         # 登录页
│   ├── customers.html     # 客户列表
│   ├── customer_detail.html # 客户详情 + 会议 + 待办
│   ├── tasks.html         # 全局待办
│   └── search.html        # 搜索结果
└── static/
    ├── css/style.css      # 自定义样式
    ├── js/
    │   ├── app.js         # 前端逻辑 + IndexedDB + 同步
    │   └── sw.js          # Service Worker
    └── manifest.json      # PWA 配置
```
# note-crm
