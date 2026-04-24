# 估值数据获取与存储

## 目标

为全部A股（~5200只）拉取5个估值指标的全部历史数据，存储为parquet文件，支持首次全量拉取和后续增量更新。

## 数据源

`akshare.stock_zh_valuation_baidu(symbol, indicator, period)`

- 全量拉取：`period="全部"`（约18天一条，从上市至今）
- 增量更新：`period="近一年"`（日频，最近365天）

indicator 参数与存储列名映射：

| indicator参数 | 存储列名 |
|---|---|
| 总市值 | total_mv |
| 市盈率(TTM) | pe_ttm |
| 市盈率(静) | pe_static |
| 市净率 | pb |
| 市现率 | pcf |

## 存储结构

```
data/valuation/A/{symbol}.parquet
```

每个文件列：`date, total_mv, pe_ttm, pe_static, pb, pcf`

日期降序排列（与K线parquet保持一致）。

## 全量拉取逻辑

1. 遍历 `data/kline/A/qfq/` 中所有symbol作为股票列表
2. 每个symbol调用5次API（5个indicator），`period="全部"`
3. 5个结果按date outer merge为一个DataFrame
4. 存入 `data/valuation/A/{symbol}.parquet`
5. 限速：每次API调用间隔适当sleep
6. 断点续传：跳过已存在的parquet文件（可选force参数强制重拉）
7. 进度报告：复用TaskManager进度机制

## 增量更新逻辑

1. 对已有parquet的symbol，读取最新date
2. 用 `period="近一年"` 拉取日频数据（5个indicator）
3. 只保留比现有最新date更新的记录
4. merge后append到现有parquet，去重后重新存储

## API接口

`POST /api/valuation/update`

请求体：
```json
{
  "mode": "full" | "incremental",
  "force": false
}
```

- `mode="full"`：全量拉取，`force=true`时重拉已存在的文件
- `mode="incremental"`：增量更新，只更新已有文件

响应：返回 task_id，通过轮询获取进度。

## 进度报告

复用现有进度机制（TaskManager + 前端轮询），报告格式：
- phase: "拉取估值数据"
- current/total: 已完成股票数/总股票数

## 前端

在数据更新页面（UpdateStatus.vue）增加估值数据更新按钮和模式选择。

## 错误处理

- 单只股票API失败不中断整体流程，记录失败列表
- 任务完成后报告成功/失败数量
- 支持重试失败的股票（下次运行自动覆盖）

## 总请求量

- 全量：~5200 × 5 = 26000次API调用
- 增量：同上（但数据量较小）

## 文件组织

- `backend/services/valuation_updater.py`：核心拉取逻辑
- `backend/routers/valuation.py`：API路由
- `backend/config.py`：新增 `VALUATION_DIR` 配置
