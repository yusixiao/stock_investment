# 历史分红数据获取与存储

## 目标

为全部A股（~5200只）拉取历史分红数据，存储为parquet文件，支持全量拉取和断点续传。

## 数据源

- **主数据源**：`ak.stock_fhps_detail_em(symbol)` — 东方财富，19列明细
- **备用数据源**：`ak.stock_history_dividend_detail(symbol, indicator='分红')` — 新浪，8列基础信息
- 每只股票先尝试东方财富，失败（超时/连接错误）则fallback到新浪

### 东方财富19列

`报告期, 业绩披露日期, 送转股份-送转总比例, 送转股份-送股比例, 送转股份-转股比例, 现金分红-现金分红比例, 现金分红-现金分红比例描述, 现金分红-股息率, 每股收益, 每股净资产, 每股公积金, 每股未分配利润, 净利润同比增长, 总股本, 预案公告日, 股权登记日, 除权除息日, 方案进度, 最新公告日期`

### 新浪8列（fallback时映射到东方财富结构）

| 东方财富列 | 新浪列 | 说明 |
|---|---|---|
| 送转股份-送股比例 | 送股 | 直接映射 |
| 送转股份-转股比例 | 转增 | 直接映射 |
| 送转股份-送转总比例 | 送股+转增 | 计算得出 |
| 现金分红-现金分红比例 | 派息 | 直接映射 |
| 预案公告日 | 公告日期 | 直接映射 |
| 股权登记日 | 股权登记日 | 直接映射 |
| 除权除息日 | 除权除息日 | 直接映射 |
| 方案进度 | 进度 | 直接映射 |
| 其余11列 | — | 填NaN |

所有parquet文件统一使用东方财富的19列schema。

## 存储结构

```
data/dividend/A/{symbol}.parquet
```

每个文件的列与东方财富接口返回的19列一致，按报告期降序排列。

## 全量拉取逻辑

1. 遍历 `data/kline/A/qfq/` 中所有symbol作为股票列表
2. 每只股票先调用东方财富接口，失败则fallback到新浪接口（映射列结构）
3. 存入 `data/dividend/A/{symbol}.parquet`
4. 断点续传：跳过已存在的parquet文件（可选force参数强制重拉）
5. 超时30秒 + 最多3次重试
6. 进度写入 `data/logs/dividend_progress.log`

## 增量更新逻辑

1. 对已有parquet的symbol，重新拉取全量数据
2. 按报告期去重后替换原文件

## API接口

`POST /api/dividend/update`

请求体：
```json
{
  "mode": "full" | "incremental",
  "force": false
}
```

`GET /api/dividend/update/status`

返回进度和结果。

## 前端

在 UpdateStatus.vue 增加分红数据更新行（全量拉取/增量更新按钮 + 进度/结果显示）。

## 错误处理

- 单只股票两个数据源都失败时记入失败列表，不中断整体流程
- 任务完成后报告成功/失败数量

## 请求量

- 全量：~5200次API调用（每只1次，远少于估值数据的26000次）

## 文件组织

- `backend/services/dividend_updater.py`：核心拉取逻辑
- `backend/routers/dividend.py`：API路由
- `backend/config.py`：新增 `DIVIDEND_DIR` 配置
