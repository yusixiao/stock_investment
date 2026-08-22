# Stock Investment Platform

个人股票投资综合平台，面向 A 股、港股和美股，覆盖行情、财务数据、选股、回测、持仓管理、策略监控和投顾场景问股。

## 功能概览

- **多市场数据**：A 股、港股、美股的行情、财务、分红、估值和复权数据。
- **行情分析**：K 线、均线、成交量、MACD 和多周期数据查看。
- **策略选股**：基于统一 `Strategy` 模型执行选股和策略雷达扫描。
- **策略回测**：事件驱动的完整交易回测，支持 T+1、手续费、滑点、涨跌停和买卖钩子。
- **策略监控**：市场数据刷新完成后自动触发策略扫描，并将结果写入历史记录。
- **持仓管理**：账户、交易、持仓、估值和定时快照。
- **问股 Agent**：面向投顾场景的多 Agent 对话和定性分析。

## Scan 与 Full

项目中的 `Strategy` 同时支持两种执行模式，但两者结果语义不同：

```text
Strategy.screen()
       ├── Scan：只观察历史日期选出的股票和因子，不进行交易
       └── Full：调用同一个 screen()，再交给 Broker 模拟交易
```

- **Scan**：回答“策略在某个历史日期会选中什么”，结果包含命中股票、因子、信号日期和扫描范围。
- **Full**：回答“按照策略交易后的组合表现如何”，结果包含收益指标、资金曲线和交易记录。

Full 回测会在自己的日期循环中调用 `screen()`，不会先运行 Scan 再把持久化 Scan 结果喂给 Full，以避免信号日期、成交日期和数据可见性错位。

## 技术架构

```text
Browser
  │
  ▼
React 19 + TypeScript + Vite + Tailwind CSS
  │ /api
  ▼
FastAPI + APScheduler
  ├── Strategy / Backtest / Monitoring
  ├── Portfolio
  ├── Agent
  └── Market Data
       ├── DuckDB 查询层
       ├── SQLite 业务库
       └── data/market/ Parquet 数据
```

### 数据访问原则

- DuckDB 是业务数据的唯一查询入口。
- 业务数据统一位于 `data/market/{A,HK,US}/`。
- `data/portfolio.db` 保存持仓、回测任务和问股相关业务数据。
- 禁止在业务代码中直接读取旧数据目录或直接扫描 Parquet 文件。
- 外部数据源使用 Baostock、Eastmoney 和 yfinance，不使用 AkShare。

## 项目结构

```text
stock_investment/
├── backend/
│   ├── main.py                 # FastAPI 应用入口
│   ├── adapters/               # 外部数据源适配器
│   ├── routers/                # HTTP 路由
│   ├── services/
│   │   ├── backtest/           # Strategy、Engine、Scan、Full、Task
│   │   ├── market_data/        # DuckDB、刷新和数据更新
│   │   ├── monitoring/         # 策略监控和价格监控
│   │   ├── portfolio/          # 持仓和账户
│   │   └── agent/              # 问股 Agent
│   └── tests/                  # 后端测试
├── frontend/
│   ├── src/components/         # React 页面和组件
│   ├── src/api/                # 前端 API 类型和请求
│   └── package.json
├── data/                       # 本地业务数据，默认不提交 Git
├── report/                     # LLM 报告和用户产物
├── logs/                       # 应用和调度日志
└── docs/                       # 设计、部署和研究文档
```

## 快速启动

### 后端

建议使用 Python 3.10 环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

启动 FastAPI：

```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

开发时也可以使用 `--reload`，但它会重启 APScheduler。需要保持定时任务稳定运行时，不要使用 `--reload`。

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认运行在 `http://localhost:3001`，Vite 会将 `/api` 请求代理到 `http://127.0.0.1:8000`。

### 数据准备

行情和财务功能依赖本地市场数据。数据刷新任务由后端 APScheduler 管理，也可以通过市场数据相关接口手动刷新。首次运行前请确认：

- `data/market/` 已存在并包含所需市场数据；
- `data/portfolio.db` 所在目录可写；
- 外部数据源和网络访问可用；
- LLM 功能已配置对应渠道和 API Key。

敏感配置不要写入 Git，也不要通过日志或 HTTP 响应暴露真实值。

## 测试与质量检查

后端：

```bash
python -m pytest backend/tests/ -x -q
```

前端：

```bash
cd frontend
npm test
npx tsc --noEmit
npm run lint
```

浏览器 Smoke Test：

```bash
cd frontend
npm run test:smoke
```

## 部署注意事项

- APScheduler 和 SQLite 业务库要求单进程运行，Uvicorn 生产环境使用 `--workers 1`。
- 问股 Agent 使用 SSE 长连接，反向代理需要关闭缓冲并设置足够长的读写超时。
- 长时间回测、批量更新和全市场任务应使用后台执行，并通过日志和任务记录观察进度。
- 生产部署细节见 [`docs/deployment.md`](docs/deployment.md)。

## 相关文档

- [`AGENTS.md`](AGENTS.md)：项目架构约束和开发铁律
- [`docs/deployment.md`](docs/deployment.md)：本地和生产部署说明
- [`backend/services/backtest/AGENTS.md`](backend/services/backtest/AGENTS.md)：回测与策略模块说明
- [`frontend/AGENTS.md`](frontend/AGENTS.md)：前端架构和测试约定
