# opt64 研究侧代码（复现用）

> 来源：`~/workspace/港股回测/`
> 用途：本地AI复现32.63%收益，然后按 `docs/opt64_strategy_migration_spec.md` 搬运到平台

## 文件

| 文件 | 说明 |
|---|---|
| `garp_opt64.py` | opt64策略完整实现（向量化引擎）|
| `engine_pit_v2.py` | PIT三层回测引擎 |
| `CHAMPION_opt64.md` | 冠军记录（含业绩、年度收益、审计结论）|
| `summary.json` | 回测结果摘要（CAGR 32.63%）|

## 复现步骤

```bash
# 需要研究侧数据（不在此repo，需单独获取）：
# - data/processed/std_v1/prices_all.parquet
# - data/processed/std_v1/prices_pit.parquet
# - data/processed/std_v1/fin_annual_only.parquet
# - data/processed/industry_user_v1.parquet
# - data/raw/all_20150101-20260930_v1.parquet

# 运行（需pandas/numpy）：
python garp_opt64.py
# 预期输出：CAGR: 32.63%, Sharpe: 1.16, MDD: -31.38%
```

## 数据说明

研究侧数据与平台`data/market/HK/`的关系：
- 研究侧用**后复权**（锚定2026-09-30）
- 平台用**前复权**（锚定最新）
- 收益率序列一致，可互换验证

v5清洗后的平台数据已验证与研究侧收益率99.97%一致（详见规格书第十节）。

## 搬运到平台

见 `docs/opt64_strategy_migration_spec.md`，目标：
```
backend/services/backtest/strategies/deployed/hk_garp_opt64_strategy.py
```
