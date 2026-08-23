# 回测平台功能裁剪设计

## 1. 目标

将系统从“股票投资综合平台”裁剪为“回测平台”，减少无关产品面和运行时依赖，同时保留回测所需的数据链路与监控能力。

本次裁剪保留：

- 策略回测
- 策略雷达
- 回测历史记录
- 盘面监控：策略监控、股票价格监控
- 策略监控定时调度
- A/HK/US 市场数据更新
- DuckDB 查询、MarketBundle、回测缓存和刷新状态
- 回测任务、刷新记录和监控记录
- 认证之外的基础运行健康检查

本次裁剪移除：

- 首页和首页 K 线展示
- 持仓账户、交易、快照、风险、现金账本和买入机会
- 问股、Agent、聊天会话和报告工作区
- 设置页、LLM/通知配置 UI 与后端路由
- 登录/认证上下文和认证路由
- 只供首页/个股详情使用的独立股票、K 线、股票搜索接口
- 旧的未被回测前端使用的 screener/analysis/history 入口
- 回测结果中的“绑定持仓账户”功能

## 2. 不变约束

- `BacktestEngine.run()` 与 `run_scan()` 的结果 schema 不变。
- `/api/backtest`、`/api/backtest/cache`、`/api/v1/monitoring` 的现有功能语义保持不变。
- 策略目录、DuckDB 唯一业务数据入口、`data/market/` 唯一路径不变。
- 监控既支持手动运行，也继续由市场刷新完成回调触发定时调度。
- 现有 `data/portfolio.db` 中的持仓、聊天、认证旧表不自动删除，也不做数据迁移破坏。
- 回测任务、监控记录和市场刷新记录继续使用现有数据库文件。

## 3. 前端设计

### 3.1 路由和入口

- `App.tsx` 移除 `AuthProvider`、登录状态分支和登录路由。
- `/backtest` 成为唯一业务页面。
- `/` 重定向到 `/backtest`。
- 未知路径重定向到 `/backtest`，不再保留首页和 NotFound 产品入口。
- 不保留单项左侧 TreeView/侧边导航；顶层只剩一个回测模块，单项导航没有信息价值。
- `Shell` 改为轻量工作区头部：左侧显示“回测平台”，中间显示四个工作区 Tab，右侧保留主题切换。
- 移动端使用紧凑顶部栏，不再打开只有一个入口的抽屉菜单。
- `/` 的内容就是回测工作区，不新增独立 Dashboard。
- 移除退出按钮、认证错误/加载态和问股完成 badge。

### 3.2 回测页

保留 `BacktestPage` 的四个 tab：

- 策略回测
- 策略雷达
- 盘面监控
- 历史记录

保留全局 `DataCacheStatusBar`，因为它是回测与监控的数据入口，不属于首页功能。

回测工作区最终布局：

```text
回测平台      策略回测  策略雷达  盘面监控  历史记录  主题切换
────────────────────────────────────────────────────────────
                         当前工作区
                                                   数据缓存状态
```

### 3.3 持仓耦合清理

- `BacktestResult` 删除账户选择、账户绑定和解绑操作。
- `BacktestHistory` 删除成功任务绑定账户的操作和相关状态。
- 删除 `portfolioApi` 在回测页面中的引用、对应类型和测试。
- 回测结果仍展示交易、权益曲线和统计指标；这些是回测引擎结果，不是持仓管理功能。

### 3.4 删除的前端模块

- `HomePage` 及其首页专属 stock/Kline 组件引用
- `ChatPage`、Agent dashboard、chat store、聊天导出和聊天专属工具
- `PortfolioPage`、portfolio API/types/utils
- `SettingsPage`、system config API/types/hooks/components
- `LoginPage`、auth API、`AuthContext`
- 仅被上述页面使用的测试和依赖引用

不删除回测组件内部使用的策略、行情、缓存和监控类型。

## 4. 后端设计

### 4.1 保留的路由

- `backtest.py`
- `backtest_cache.py`
- `monitoring.py`
- `market_update.py`
- `meta.py` 中仍服务数据更新/完整性诊断的入口
- `hk_connect.py`，因为港股通是回测市场过滤能力
- 健康检查

### 4.2 删除的路由

- `portfolio_v1.py`
- `agent.py`
- `system_config.py`
- `auth_stub.py`
- `stock.py`
- `stock_search.py`
- `market_kline.py`
- `screener.py` 中已由 `/api/backtest/scan-radar` 替代且无保留前端调用的旧入口

删除前通过全仓库引用检查确认没有保留前端、scheduler 或监控实现依赖这些路由。

### 4.3 启动与调度

启动生命周期保留：

- DuckDB 初始化与健康检查
- stock index 初始化
- backtest task 表初始化
- market refresh 状态表初始化
- monitoring 表初始化
- A 股 MarketBundle 异步预加载
- scheduler 启动

启动生命周期删除：

- `services.portfolio.db.init_db()`
- portfolio schema 初始化
- chat schema 初始化
- 认证相关装配

`scheduler.py` 保留：

- 市场刷新
- 刷新失败重试
- 策略监控调度
- 股票价格监控评估

`scheduler.py` 删除：

- 持仓快照任务
- 买入机会评估
- 所有 portfolio import

### 4.4 SQLite schema 拆分

当前 `init_portfolio_v1_tables()` 同时创建 portfolio 表和 monitoring 表。裁剪时拆成：

- `init_backtest_tables()`：只负责 `backtest_tasks`、`stock_exclusions`。
- `init_market_refresh_tables()`：负责市场刷新生命周期。
- 新增 `init_monitoring_tables()`：负责四张 monitoring 表及其约束/索引迁移。
- portfolio/chat 的 schema 函数不再由运行时调用；旧表保留在现有数据库中。

监控 repository、strategy monitor、stock price monitor 改为调用 `init_monitoring_tables()`，不能再通过 portfolio module 间接初始化监控表。

## 5. 数据流

```text
market updater
    -> RefreshRunner
    -> DuckDB views / MarketBundle cache
    -> backtest / radar
    -> monitoring scheduler
    -> monitoring strategy runs / stock events
```

回测平台不再有：

```text
market refresh -> portfolio snapshot -> buy opportunity
```

监控仍保留：

```text
market refresh -> successful market stages -> strategy monitor scheduling
market refresh -> successful market stages -> stock price monitor evaluation
```

## 6. 数据接口裁剪原则

- 内部数据读取继续经过 `DuckDBStore` 和 `data_cache`。
- 删除独立首页/个股详情的 K 线与股票搜索 HTTP 接口。
- 监控需要股票名称时继续使用内部 stock index，不恢复完整股票查询路由。
- 不为本次裁剪新增兼容路由或重定向 API。
- 旧数据库表只保留数据，不向 HTTP 暴露旧功能。

## 7. 测试策略

后端：

- 保留并更新回测、任务、缓存、市场刷新、监控、策略监控、股票价格监控测试。
- 新增 schema 测试，验证新数据库会创建 backtest/refresh/monitoring 表，不创建 portfolio/chat 表。
- 验证旧数据库存在 portfolio/chat 表时，启动 bootstrap 不删除它们。
- 验证刷新完成仍触发监控调度，但不触发 portfolio snapshot 或 buy opportunity。
- 删除 portfolio/agent/system-config/auth/router 测试及其 fixture 引用。

前端：

- 更新 App 路由测试：`/` 重定向 `/backtest`，未知路径重定向 `/backtest`。
- 更新 Shell/导航测试：只有回测入口，无认证和退出入口。
- 保留 BacktestPage、回测配置/结果/历史/雷达/监控测试。
- 删除 Home、Portfolio、Chat、Settings、Login 相关测试。
- 验证回测结果不再触发 portfolio 请求。

验证命令：

```bash
python -m pytest backend/tests/ -x -q
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
cd frontend && npm run test:smoke
```

## 8. 风险与回滚

- 风险：monitoring schema 过去依赖 portfolio 初始化，拆分时可能漏掉旧库约束迁移。
  - 缓解：复用现有 monitoring constraint migration，增加旧库 fixture 测试。
- 风险：回测结果页面仍存在隐性 portfolio import。
  - 缓解：全仓库搜索 `portfolioApi`、`services.portfolio` 和 account binding 文案，并运行类型检查。
- 风险：scheduler 仍间接导入 portfolio。
  - 缓解：删除 import 后用 scheduler 单元测试验证刷新回调。
- 回滚：代码回滚不会删除 SQLite 旧表；旧数据仍在 `data/portfolio.db` 中。

## 9. 完成标准

- 访问 `/` 直接进入回测页面。
- 前端无首页、持仓、问股、设置、登录入口。
- 后端不注册上述删除路由，启动不初始化上述删除 module。
- 回测、雷达、历史、盘面监控和监控调度均可用。
- 市场数据刷新、DuckDB、缓存和港股通过滤不受影响。
- 旧 portfolio/chat/auth 数据未被删除。
- 全部相关测试、类型检查、lint 和 smoke 通过。
