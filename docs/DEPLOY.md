# FontCop 部署指南

标准 HTTP 服务 + 纯静态前端，任意进程托管/反向代理均可。以下为最小可用配置。

## 快速检查

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.indexer          # 首次建索引
FONTOP_HOST=0.0.0.0 .venv/bin/python -m src.server
curl http://127.0.0.1:8642/healthz       # → {"status":"ok","version":...}
```

## systemd（推荐，Linux）

`/etc/systemd/system/fontcop.service`：

```ini
[Unit]
Description=FontCop font license matcher
After=network.target

[Service]
WorkingDirectory=/opt/fontcop
Environment=FONTOP_HOST=127.0.0.1
Environment=FONTOP_TOKEN=change-me
ExecStart=/opt/fontcop/.venv/bin/python -m src.server
Restart=on-failure
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now fontcop
```

## Caddy（HTTPS + 限流，自动证书）

```caddyfile
font.yourexample.com {
    reverse_proxy 127.0.0.1:8642
    rate_limit {
        zone api {
            key {remote_host}
            events 30
            window 1m
            allowed 30
        }
        match_path /api/*
    }
    encode gzip zstd
}
```

## nginx

```nginx
server {
    listen 443 ssl;
    server_name font.yourexample.com;
    # ssl_certificate / ssl_certificate_key ...
    location / {
        proxy_pass http://127.0.0.1:8642;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    limit_req_zone $binary_remote_addr zone=fontcop:10m rate=30r/m;
    location /api/ { limit_req zone=fontcop burst=10 nodelay; }
}
```

## 可选项

- **关掉 OCR**：加 `Environment=FONTOP_NO_OCR=1` 即可不装/不加载 rapidocr，前端退回手动框选，镜像与内存都更小。
- **多 worker**：对识别吞吐不敏感可一直用单进程（ThreadingHTTPServer + OCR 锁）。并发真上去了再研究多进程/换 ASGI（当前代码无需改动，handler 是框架无关的）。
- **不落历史**：删除/只读挂载 `data/history.jsonl` 即可禁用识别历史。