# Teemo G1 后端服务器

这是一个基于 Django 框架构建的、用于支持 Teemo G1 的后端服务器。项目部分复现了手表与服务器之间的通信协议，包括基于 SSL/TLS 的 TCP 长连接服务和 HTTP API 接口。

## 功能介绍

本项目实现了儿童手表所需的部分后端功能，主要包括：

1.  **高并发 TCP 长连接服务**:
    *   使用 Django Channels 和 `asyncio` 构建了一个异步、非阻塞的 TCP 服务器。
    *   支持 SSL/TLS 加密通信，确保数据传输安全。
    *   实现了手表的核心通信协议，处理登录、心跳、状态上报等关键操作。

2.  **核心业务功能**:
    *   **设备管理**: 处理设备登录认证、信息更新（版本、IMEI等），并为每个设备生成唯一的 `baby_id` 和 `http_token`。
    *   **定位服务**:接收并持久化手表上报的定位数据包。
    *   **即时通讯 (Chat)**:
        *   支持接收文本、语音、图片等多种类型的聊天消息。
        *   自动保存上传的语音和图片文件到服务器。
        *   实现了消息确认（ACK）机制，确保消息可靠送达。
    *   **通讯录管理**:
        *   通过 HTTP API 实现对设备联系人的增、删、改、查操作。
        *   利用 Redis Pub/Sub 机制，在联系人变更后，通过 TCP 长连接实时将更新推送到手表端。
    *   **通话记录**: 接收并存储手表的通话记录。
    *   **其他辅助功能**: 实现了天气信息、应用列表、版本检查等辅助接口。

3.  **后台管理系统**:
    *   基于 Django Admin，提供了功能完善的后台管理界面。
    *   可以方便地查看和管理所有设备、定位数据、联系人、通话记录和聊天日志。
    *   特别优化了聊天记录的展示，可以直接在后台播放语音消息、预览图片。
    *   在设备详情页内嵌显示最新的定位历史记录，方便追踪。

## 使用方法

### 1. 环境准备

*   Python 3.8+
*   Redis Server
*   Git

### 2. 项目设置

1.  **克隆仓库**
    ```bash
    git clone
    cd WEEEServer
    ```

2.  **创建并激活虚拟环境**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS / Linux
    source venv/bin/activate
    ```

3.  **安装依赖**
    建议创建一个 `requirements.txt` 文件并包含以下内容：
    ```
    # requirements.txt
    Django
    channels
    channels_redis
    daphne
    djangorestframework
    redis
    pycryptodome
    ```
    然后运行安装命令：
    ```bash
    pip install -r requirements.txt
    ```

4.  **配置**
    打开 `WEEEServer/settings.py`，根据你的网络环境修改 `ALLOWED_HOSTS`，例如：
    ```python
    ALLOWED_HOSTS = ['192.168.2.99', '127.0.0.1', 'localhost']
    ```
    
### 3. 数据库迁移

1.  **初始化数据库**
    ```bash
    python manage.py migrate
    ```

2.  **创建后台管理员账户**
    ```bash
    python manage.py createsuperuser
    ```
    按照提示输入用户名、邮箱和密码。

### 4. 运行服务

你需要同时启动 **3个** 服务：Redis、Django HTTP 服务器和自定义的 TCP 服务器。

1.  **启动 Redis**
    确保你的 Redis 服务器正在运行。

2.  **启动 Django HTTP 服务器** (用于 Admin 后台和 API)
    ```bash
    python manage.py runserver 0.0.0.0:8000
    ```

3.  **启动 TCP 服务器** (在另一个终端中)
    ```bash
    python manage.py run_tcp_server
    ```
    如果一切正常，你将看到 `[*] TLS/TCP 服务器正在 ('0.0.0.0', 5001) 上监听...` 的输出。

### 5. 访问后台

现在，你可以通过浏览器访问 `http://你的IP:8000/admin/` 来进入 Django 管理后台，使用之前创建的管理员账户登录。

## 部署方式

在生产环境中，推荐使用 Nginx + Gunicorn + Systemd 的组合进行部署。

### 1. 基础配置

*   修改 `WEEEServer/settings.py`：
    *   `DEBUG = False`
    *   `ALLOWED_HOSTS = ['your_domain.com', 'your_server_ip']`
    *   `SECRET_KEY` 应从环境变量或配置文件中读取，不要硬编码。
*   使用由权威机构签发的真实 SSL 证书，替换自签名的 `server.crt` 和 `server.key`。

### 2. Gunicorn (HTTP服务)

Gunicorn 是一个高效的 Python WSGI HTTP 服务器。

```bash
pip install gunicorn
# 在项目根目录下运行 Gunicorn
gunicorn --workers 3 --bind unix:/run/gunicorn.sock WEEEServer.wsgi:application
```

### 3. Systemd (进程守护)

使用 `systemd` 来管理 Gunicorn 和 TCP 服务器进程，确保它们可以开机自启并在崩溃后自动重启。

**Gunicorn 服务 (`/etc/systemd/system/gunicorn.service`):**
```ini
[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
User=your_user
Group=www-data
WorkingDirectory=/path/to/your/project
ExecStart=/path/to/your/project/venv/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:/run/gunicorn.sock \
          WEEEServer.wsgi:application

[Install]
WantedBy=multi-user.target
```

**TCP 服务器服务 (`/etc/systemd/system/tcp_server.service`):**
```ini
[Unit]
Description=Teemo Watch TCP Server
After=network.target

[Service]
User=your_user
Group=your_user
WorkingDirectory=/path/to/your/project
ExecStart=/path/to/your/project/venv/bin/python manage.py run_tcp_server
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**启用并启动服务:**
```bash
sudo systemctl daemon-reload
sudo systemctl start gunicorn tcp_server
sudo systemctl enable gunicorn tcp_server
```

### 4. Nginx (反向代理)

Nginx 负责处理所有外部请求，并将它们转发给内部服务。

*   **HTTP 请求** -> 转发给 Gunicorn。
*   **TCP 请求** -> 转发给自定义的 TCP 服务器。
*   直接提供**静态文件**和**媒体文件**。

**示例 Nginx 配置 (`/etc/nginx/sites-available/weeeserver`):**

```nginx
# 必须在 nginx.conf 的顶层添加 stream 模块
# stream {
#     ...
# }

stream {
    upstream tcp_backend {
        server 127.0.0.1:5001;
    }

    server {
        listen 5001 ssl;  # 对外暴露的TCP端口
        proxy_pass tcp_backend;

        # 配置 SSL 证书
        ssl_certificate /path/to/your/fullchain.pem;
        ssl_certificate_key /path/to/your/privkey.pem;
        ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3;
        ssl_ciphers 'DEFAULT:@SECLEVEL=0'; # 兼容旧设备
    }
}


server {
    listen 80;
    listen [::]:80;
    server_name your_domain.com;
    # 强制跳转到 HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name your_domain.com;

    # SSL 证书配置
    ssl_certificate /path/to/your/fullchain.pem;
    ssl_certificate_key /path/to/your/privkey.pem;

    location = /favicon.ico { access_log off; log_not_found off; }

    # 静态文件
    location /static/ {
        root /path/to/your/project;
    }

    # 媒体文件 (用户上传的语音、图片)
    location /media/ {
        root /path/to/your/project;
    }

    # HTTP API 和 Admin 后台
    location / {
        proxy_pass http://unix:/run/gunicorn.sock;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```