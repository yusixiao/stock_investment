# 数据管理 + K 线可视化 — 设计文档

## 概述

个人自用的 A 股投资综合平台的第一个子项目：数据管理与 K 线可视化。基于现有的 5212 只 A 股 K 线 parquet 数据，构建 Web 界面，提供每日增量数据更新、股票浏览和 K 线图表展示。

## 技术栈

- **后端**: Python + FastAPI
- **前端**: Vue 3 (Composition API) + ECharts
- **数据源**: AKShare (`stock_zh_a_spot_em`)
- **数据存储**: Parquet 文件 (`data/kline/A/raw/{代码}.parquet`)
- **定时任务**: APScheduler

## 现有数据格式

每只股票一个 parquet 文件，日期降序排列：

| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 日期，如 `2026-04-10` |
| open | float64 | 开盘价 |
| high | float64 | 最高价 |
| low | float64 | 最低价 |
| close | float64 | 收盘价 |
| volume | float64 | 成交量 |
| amount | float64 | 成交额 |

文件命名: `{代码}.{交易所}.parquet`，如 `600028.SH.parquet`、`300163.SZ.parquet`

## 功能模块

### 1. 每日增量数据更新

#### 1.1 核心流程

1. 调用 `ak.stock_zh_a_spot_em()` 一次性获取全部 A 股当日行情（约 5000+ 行）
2. 从返回数据中提取：代码、日期、开盘价、最高价、最低价、收盘价、成交量、成交额
3. 遍历结果，对每只股票：
   - 根据代码前缀映射交易所后缀（6 开头 → SH，其余 → SZ）构造文件名
   - 读取对应 parquet 文件的最新日期（第一行，降序）
   - 当日数据日期 > 最新日期 → 追加到文件头部，保持降序
   - 当日数据日期 <= 最新日期 → 跳过
4. 记录更新日志

#### 1.2 代码与交易所映射

- `6xxxxx` → `SH`（上海）
- `0xxxxx`, `3xxxxx` → `SZ`（深圳）
- `4xxxxx`, `8xxxxx` → `BJ`（北京，当前数据中不包含，暂不处理）

#### 1.3 字段映射

AKShare spot 接口返回的中文列名需映射到现有 parquet 格式：

| spot 接口字段 | parquet 字段 |
|--------------|-------------|
| 代码 | (用于定位文件) |
| 今开 | open |
| 最高 | high |
| 最低 | low |
| 最新价 | close |
| 成交量 | volume |
| 成交额 | amount |
| (当日日期) | date |

#### 1.4 重试机制

API 调用采用指数退避重试策略：

- 最大重试次数: **20 次**
- 退避策略: 指数递增，`wait = min(2^attempt, 60)` 秒
- 即: 1s, 2s, 4s, 8s, 16s, 32s, 60s, 60s, ...
- 每次重试记录日志
- 20 次全部失败则记录错误并抛出异常

#### 1.5 触发方式

- **定时自动**: 内置 APScheduler，默认每交易日 15:30 自动执行
- **手动触发**: Web 页面"立即更新"按钮，调用 `POST /api/data/update` 触发
- **状态展示**: 页面显示上次更新时间、更新状态（空闲/进行中/成功/失败）、更新详情（成功数/跳过数/失败数）

#### 1.6 新股处理

如果 spot 接口返回的股票在 `data/kline/A/raw/` 中没有对应文件，自动创建新文件，写入当日数据。

#### 1.7 非交易日保护

非交易日 spot 接口返回上一个交易日的数据，通过日期比较自动跳过，不会重复写入。

### 2. 更新日志

每次更新记录：

- 更新触发时间
- 触发方式（定时/手动）
- API 调用耗时、重试次数
- 成功更新股票数
- 跳过股票数（已是最新）
- 失败股票数及失败原因
- 新增股票数

日志持久化到 `data/logs/update_log.json`，保留最近 90 天。

### 3. 股票列表浏览

- 展示所有股票列表：代码、名称、最新价、涨跌幅、成交量
- 支持按代码或名称搜索
- 分页展示
- 点击股票跳转到 K 线详情页

### 4. 数据完整性检查

- 检测缺失交易日（与交易日历对比）
- 检测异常数据：空值、负值、开高低收逻辑错误（如 high < low）
- 提供 API 接口和页面展示检查结果

### 5. K 线可视化

#### 5.1 K 线图

- 蜡烛图展示开高低收
- 底部成交量柱状图
- 支持时间区间选择（日期范围选择器）
- 支持鼠标滚轮缩放、拖拽平移
- 十字光标 + 数据提示框

#### 5.2 技术指标

叠加在 K 线图上或独立子图展示：

- **MA**: 移动平均线（5/10/20/60 日）
- **MACD**: 异同移动平均线（包含 DIF、DEA、MACD 柱状图）
- **KDJ**: 随机指标
- **BOLL**: 布林带

指标计算在后端完成，前端负责渲染。用户可在页面上勾选/取消指标。

## 架构设计

### 项目结构

```
stock_investment/
├── data/
│   ├── kline/A/raw/          # 现有 parquet 数据
│   └── logs/                  # 更新日志
├── backend/
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 配置（调度时间、数据路径等）
│   ├── routers/
│   │   ├── stock.py          # 股票列表、K 线数据 API
│   │   └── data_update.py    # 数据更新触发、状态查询 API
│   ├── services/
│   │   ├── data_updater.py   # 增量更新核心逻辑
│   │   ├── stock_data.py     # parquet 读取、查询
│   │   └── indicator.py      # 技术指标计算
│   ├── scheduler.py          # APScheduler 定时任务
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── StockList.vue     # 股票列表页
│   │   │   └── StockDetail.vue   # K 线详情页
│   │   ├── components/
│   │   │   ├── KlineChart.vue    # K 线图组件
│   │   │   ├── UpdateStatus.vue  # 更新状态组件
│   │   │   └── SearchBar.vue     # 搜索栏组件
│   │   └── ...
│   └── package.json
└── docs/
```

### API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 股票列表（支持搜索、分页） |
| GET | `/api/stocks/{symbol}/kline` | 某只股票的 K 线数据（支持日期范围） |
| GET | `/api/stocks/{symbol}/indicators` | 技术指标数据 |
| POST | `/api/data/update` | 手动触发数据更新 |
| GET | `/api/data/update/status` | 查询更新状态 |
| GET | `/api/data/update/logs` | 查询更新日志 |
| GET | `/api/data/health` | 数据完整性检查结果 |

### 数据流

```
AKShare API → data_updater.py → parquet 文件
                                      ↓
前端 Vue ← FastAPI REST API ← stock_data.py / indicator.py
```

## 非功能需求

- **性能**: parquet 读取使用 Pandas，单文件读取应在 100ms 内完成
- **并发**: 数据更新过程中 API 仍可正常响应读请求
- **错误处理**: API 调用失败不影响已成功更新的数据，更新过程中单个文件写入失败不中断整体流程
