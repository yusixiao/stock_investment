# QFQ 数据重构：从源数据到缓存模式

## 背景

当前系统维护两份 K 线数据：`data/kline/A/raw/`（不复权）和 `data/kline/A/qfq/`（前复权）。日常增量更新通过 `stock_zh_a_spot_em` 只能获取不复权的当日行情，无法正确增量更新 qfq 数据。前复权数据在发生除权除息时需要全量重算历史价格，无法简单追加。

## 核心思路

将 `data/kline/A/qfq/` 从"源数据"变为"缓存"，由 raw 数据 + dividend 复权因子实时计算生成。

## 数据源

- **raw 数据**：`data/kline/A/raw/{symbol}.parquet` — 不复权 OHLCV，日常增量更新
- **dividend 数据**：`data/dividend/A/{symbol}.parquet` — 分红送转记录，月度更新（已有前端入口）

## 复权因子计算公式

对每个已实施的除权除息日 `d`：

```
字段映射（dividend parquet）：
  "现金分红-现金分红比例" → 每10股派息金额（元），如 3.62 表示每10股派 3.62 元
  "送转股份-送股比例"   → 每10股送股数
  "送转股份-转股比例"   → 每10股转股数

每股派息 = "现金分红-现金分红比例" / 10
每股送股 = "送转股份-送股比例" / 10
每股转股 = "送转股份-转股比例" / 10
pre_close = raw 数据中除权除息日前一个交易日的收盘价

单次因子 = (pre_close - 每股派息) / (pre_close × (1 + 每股送股 + 每股转股))
```

累积因子（前复权以最新日为基准，因子=1）：

```
某交易日的累积因子 = 该日之后所有除权日的单次因子连乘
qfq_price = raw_price × 累积因子
```

## 缓存机制

### 缓存文件
- 位置：`data/kline/A/qfq/{symbol}.parquet`
- 元信息：`data/kline/A/qfq/_meta.json`

### _meta.json 结构
```json
{
  "000001.SZ": {"last_ex_date": "2025-10-15", "raw_latest_date": "2026-04-10"},
  "000002.SZ": {"last_ex_date": "2025-06-12", "raw_latest_date": "2026-04-10"}
}
```

### 缓存有效性判断

读取 qfq 数据时：
1. 从 dividend 获取该股票最新已实施除权日
2. 从 raw 获取最新日期
3. 与 meta 中记录的值比对：
   - 除权日未变 & raw 无新数据 → 缓存有效，直接返回
   - 仅 raw 有新数据（无新除权）→ 追加新日期数据到缓存（当日 raw = qfq）
   - 有新除权 → 全量重算并写入缓存

## 关键流程

### 1. 读取 qfq 数据（K线展示/回测）

```
get_qfq_kline(symbol, start_date?, end_date?) →
  检查缓存有效性
  有效 → 读取缓存 parquet 返回
  仅需追加 → 读取缓存 + 追加新日期 raw 数据 → 更新缓存 → 返回
  需重算 → 从 raw + dividend 全量计算 → 写入缓存 → 返回
```

### 2. 日常行情更新（data_updater）

```
raw 追加当日数据 → 同时追加到 qfq 缓存 → 更新 _meta.json 中 raw_latest_date
```

### 3. dividend 更新后

```
对比新旧除权记录 → 有新除权的股票删除其 qfq 缓存文件并清除 meta 条目 → 下次访问时自动重算
```

## 新增模块

### `services/qfq_cache.py`

- `get_qfq_kline(symbol, start_date=None, end_date=None) -> pd.DataFrame` — 核心入口
- `compute_qfq(symbol) -> pd.DataFrame` — 从 raw + dividend 全量计算前复权数据
- `invalidate_cache(symbols: list[str])` — 删除指定股票的 qfq 缓存
- `invalidate_all()` — 清空全部 qfq 缓存
- `get_latest_ex_date(symbol) -> str | None` — 从 dividend 读取最新已实施除权日

## 改动范围

### 修改
- `routers/stock.py` — K 线接口 adjust=qfq 时调用 qfq_cache
- `services/backtest/engine.py` — 回测加载数据时调用 qfq_cache
- `services/data_updater.py` — raw 更新后追加 qfq 缓存
- dividend 更新服务 — 更新完成后联动清理受影响股票的 qfq 缓存

### 不变
- `data/kline/A/raw/` — 数据源不变
- `data/dividend/A/` — 数据源不变
- 前端 — API 接口签名不变，前端无需改动
- 回测 API — 返回格式不变

## 验证方案

1. 重构前将现有 `data/kline/A/qfq/` 重命名为 `data/kline/A/qfq_validation/`
2. 用新的复权计算逻辑从 raw + dividend 重新生成全部 qfq 数据到 `data/kline/A/qfq/`
3. 随机选取 30 只股票，逐日对比 qfq 与 qfq_validation 的 OHLC 数据
4. 验证通过后，`qfq_validation/` 可删除

## 性能考量

- 复权计算本身是向量乘法，单只股票 < 10ms
- 瓶颈在 IO（读取 parquet），缓存机制避免重复计算
- 回测场景：首次访问时按需计算并缓存，后续直接读缓存
- 日常场景：增量追加，几乎无额外开销
