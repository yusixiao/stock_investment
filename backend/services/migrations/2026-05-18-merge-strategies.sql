-- Migration: 2026-05-18-merge-strategies (Phase 4.7 + 6.3)
--
-- 1) backtest_tasks: 新增 is_deleted (软删, 与遗留 deleted 列并存)
--    + log_dir (本次任务日志目录, nullable)
-- 2) pipeline_info 旧格式 {pipeline: [{class_name, params}]} 迁移为
--    新格式 {strategy_class, params} (merge-strategies 单策略模型)
--    仅迁移确实匹配旧形态的行;新形态 {strategies, ...} 留待 router 层改造
-- 3) DROP strategy_groups / group_runs (Phase 6.3, T6.3):
--    策略组(StrategyGroup)子系统已废弃,业务代码 + 路由 + 测试已删除。
--    幂等: IF EXISTS 保证旧库可清理、新库不报错。
--
-- 注意: 该文件为参考性 SQL;实际执行由 db_schema.run_merge_strategies_migration()
-- 通过 PRAGMA table_info 做幂等检查后下发,确保多次启动不重跑。

ALTER TABLE backtest_tasks ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE backtest_tasks ADD COLUMN log_dir TEXT;

-- 同步遗留 deleted 列到 is_deleted (新代码统一读 is_deleted)
UPDATE backtest_tasks SET is_deleted = deleted WHERE is_deleted = 0 AND deleted = 1;

-- pipeline_info 旧格式 -> 新格式
UPDATE backtest_tasks
SET pipeline_info = json_object(
    'strategy_class', json_extract(pipeline_info, '$.pipeline[0].class_name'),
    'params', json_extract(pipeline_info, '$.pipeline[0].params')
)
WHERE pipeline_info IS NOT NULL
  AND json_extract(pipeline_info, '$.pipeline') IS NOT NULL;

-- DROP 已废弃的策略组表
DROP TABLE IF EXISTS group_runs;
DROP TABLE IF EXISTS strategy_groups;
