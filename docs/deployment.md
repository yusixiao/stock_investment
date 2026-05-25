# Deployment Notes

部署相关说明。dev 环境只需 vite + uvicorn 直接起;prod 部署到 nginx/Docker/公司网关时,**SSE 长连接**与**调度器进程模型**是两个最容易踩坑的点。

## 拓扑

```
┌─────────┐       ┌──────────┐       ┌────────────┐
│ Browser │ ───── │  Nginx   │ ───── │  Uvicorn   │
│ (SSE)   │  443  │ (TLS+    │  8000 │  FastAPI   │
└─────────┘       │  reverse │       │  + APSched │
                  │  proxy)  │       └─────┬──────┘
                  └──────────┘             │
                                           ▼
                                    ┌────────────┐
                                    │ data/ +    │
                                    │ DuckDB +   │
                                    │ portfolio. │
                                    │   db       │
                                    └────────────┘
```

## SSE 长连接(关键)

问股 LLM Pipeline(Phase 1 数据包 → Phase 3.1 量化 → Phase 3.2 估值)单次完整跑完可达 **5-15 分钟**,期间需要 SSE(`text/event-stream`)持续推送 `tool_start / tool_done / generating / done` 事件。任何中间层缓冲、超时、连接复用问题都会导致前端"卡住"或假死。

### 后端已做的防御(`backend/routers/agent.py`)

```python
headers = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",     # 关键:nginx 看到此头会关 proxy_buffering
    "Connection": "keep-alive",
}
return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
```

`gen()` 还有 **15s 心跳**(`asyncio.wait_for(queue.get(), 15)` 超时发 `: ping\n\n`),保护 Phase 切换间隔被任何中间件断开。EventSource / fetch 都会忽略注释行,业务无感知。

### Vite dev server proxy(`frontend/vite.config.ts`)

```ts
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
      timeout: 0,         // socket idle 不超时
      proxyTimeout: 0,    // 上游不超时
      ws: false,
    },
  },
}
```

http-proxy 默认就是 0=不限,这里**显式声明防回归**。改完需要重启 `npm run dev`。

### Nginx 配置(部署到 prod 时使用)

```nginx
location /api/v1/agent/chat/stream {
    proxy_pass http://backend:8000;

    # SSE 必备
    proxy_http_version 1.1;
    proxy_buffering off;             # 配合后端 X-Accel-Buffering: no
    proxy_cache off;
    proxy_set_header Connection "";  # 清空让 keep-alive 生效
    chunked_transfer_encoding on;

    # 长连接超时:LLM 单阶段最长可达数分钟
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
    proxy_connect_timeout 60s;

    # 透传客户端信息
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# 普通 API 路径用普通配置即可
location /api/ {
    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

### 客户端(浏览器)注意

- 当前前端用 `fetch` + ReadableStream 解析 SSE(`frontend/src/api/agent.ts::chatStream`),非 EventSource。fetch 没有内置心跳重连,需要在 `useTaskStream` hook 里处理网络断开后的重连(目前是简单 fail-fast,生产前需补)
- 客户端到 nginx 之间如果有公司网关 / CDN(Cloudflare 等),还要确认它们对 `text/event-stream` 不缓冲。Cloudflare 默认会缓冲非 200 状态,建议加 Page Rule "Cache Level: Bypass"

## Uvicorn 进程模型

### dev(本地)

```bash
cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**坑**:`--reload` 监听文件变化重启 worker,但**会重置 APScheduler 调度器**(scheduler 在 lifespan 里创建,worker 重启就丢)。如果某次重启失败或卡住,定时任务(每天 06:00 市场更新 / 15:30 持仓快照 / 周日 03:00 备份)会**静默不跑**。

**症状识别**:
- `data/market/*/daily/*.parquet` mtime 不再每日刷新
- `logs/app.log` 在某个时间点之后没有 `_market_update_job` 触发记录
- 进程仍在但 `/api/health` 200(因为 worker HTTP 路由活着,只是 scheduler 死了)

**修复**:杀掉进程,**用无 `--reload` 模式**起一次让 scheduler 稳跑(实际开发时再换回 `--reload`)。或:
```bash
cd backend && nohup python -m uvicorn main:app --host 127.0.0.1 --port 8000 \
    > /tmp/uvicorn.log 2>&1 &
```

### prod(单机)

```bash
cd backend && python -m uvicorn main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 \
    --log-config logging.yaml
```

**关键**:`--workers` 必须是 **1**。多 worker 会:
1. 每个 worker 都跑一份 APScheduler → 定时任务**重复执行**
2. 每个 worker 都尝试写 `portfolio.db` SQLite → 锁竞争
3. 每个 worker 都加载 MarketBundle 全市场数据 → 内存翻倍

如需横向扩容,正确做法是把**调度器拆出独立进程**(单独跑 `python -m backend.scheduler_main`),uvicorn 多 worker 只跑 HTTP。当前代码尚未做这种拆分。

### systemd unit(推荐)

`/etc/systemd/system/stock-investment.service`:

```ini
[Unit]
Description=Stock Investment FastAPI Backend
After=network.target

[Service]
Type=simple
User=stock
WorkingDirectory=/opt/stock_investment/backend
Environment="PATH=/opt/stock_investment/.venv/bin"
Environment="DSA_PORTFOLIO_DB=/opt/stock_investment/data/portfolio.db"
ExecStart=/opt/stock_investment/.venv/bin/python -m uvicorn main:app \
    --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=10
StandardOutput=append:/opt/stock_investment/logs/app.log
StandardError=append:/opt/stock_investment/logs/app.log

[Install]
WantedBy=multi-user.target
```

## 数据 / 备份

按 AGENTS.md 「项目结构铁律(2026-05-24)」四类目录:

| 目录 | 内容 | 备份策略 |
|---|---|---|
| `data/` | parquet 行情/财务/分红/估值 + `portfolio.db` | **每周备份**(周日 03:00 自动到百度网盘 via `scripts/backup_to_baidu.py`) |
| `report/` | LLM 生成的分析报告(花 token 的 artifact) | **每周备份** |
| `cache/` | 纯派生缓存(tavily / qfq) | 不备份,可随时删 |
| `logs/` | 应用 / 调度器日志 | 不备份,定期清理(>30 天) |

## 配置(`config/system_config.yaml`)

部署后必须配置的 9 个 key:

```yaml
LLM_DEFAULT_CHANNEL: openrouter
LLM_OPENROUTER_PROVIDER: openrouter
LLM_OPENROUTER_BASE_URL: https://openrouter.ai/api/v1
LLM_OPENROUTER_API_KEY: sk-or-xxx     # 敏感
LLM_OPENROUTER_MODEL: deepseek/deepseek-chat
LLM_OPENROUTER_MAX_TOKENS: 8192
LLM_OPENROUTER_TEMPERATURE: 0.3
LLM_OPENROUTER_TIMEOUT: 120
TAVILY_API_KEY: tvly-xxx              # 敏感(可选,无 key 优雅降级)
```

敏感字段不通过 HTTP 下发真实值。运维改 yaml 后:
- 若想**热生效**:`POST /api/system-config` 接口(从 yaml 重 load)
- 否则:重启 uvicorn

## 健康检查

| 端点 | 用途 |
|---|---|
| `GET /api/health` | 进程存活(返回 `{"status":"ok"}`) |
| `GET /api/meta/duckdb/diag` | DuckDB 视图健康 + 行数 |
| `GET /api/market-update/progress` | 当前/最近一次市场更新进度(内存,重启后清零) |

部署后建议在监控里盯:
1. `/api/health` 5xx 或超时
2. `data/market/A/daily/*.parquet` mtime 距今 > 36h(说明 06:00 调度器没跑)
3. `data/portfolio.db` 锁等待
4. `logs/app.log` 中 `ERROR` / `Traceback` 关键字
