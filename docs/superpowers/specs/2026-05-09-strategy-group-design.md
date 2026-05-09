# 策略组（Strategy Group）设计文档

## 概述

新增「策略组」实体，将策略的有序线性链封装为可重复执行的单元。解决当前回测系统中策略间关联关系不直观、历史运行无法有效追踪的问题。

## 概念模型

- **策略（Strategy）**：单一的 ScreenerStrategy 或 TraderStrategy，最小执行单元
- **策略组（Strategy Group）**：策略的有序线性链 + 策略间关联关系定义，是调度执行的最小单元
- **任务/运行（Run）**：策略组的一次运行实例，绑定具体参数和日期范围，产出各步骤结果

关系：`策略组 1:N 运行`，`策略组 1:N 策略（有序线性链）`

## 页面结构

### 导航栏

- A股列表
- **策略调试**（原 ScreenerPage 改造，单策略运行/验证，结果存 DB）
- **回测**（策略组管理，正式执行入口）
- 组合管理

### 路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/backtest` | StrategyGroupList | 策略组列表（第1层） |
| `/backtest/group/create` | StrategyGroupEdit | 创建策略组 |
| `/backtest/group/:groupId/edit` | StrategyGroupEdit | 编辑策略组 |
| `/backtest/group/:groupId` | StrategyGroupDetail | 运行历史（第2层） |
| `/backtest/group/:groupId/run/:runId` | RunDetail | 步骤详情（第3层） |
| `/debug` | StrategyDebug | 策略调试页（原 ScreenerPage 改造） |

### 第1层：策略组列表 (`/backtest`)

- 顶部：「+ 创建策略组」按钮 + 「迁移历史任务」按钮
- 卡片列表，每张卡片展示：
  - 策略组名称（可点击进入第2层）
  - 策略链路流程图（类型标签 + 频率标签 + 策略名 + 关联模式箭头）
  - 摘要：已运行 N 次 | 最近运行日期 | 最近结果
  - 操作：运行按钮（弹出日期范围 + 执行模式选择）
  - 点击卡片 → 跳转到 `/backtest/group/:groupId`

### 第2层：运行历史 (`/backtest/group/:groupId`)

- 顶部：返回按钮 + 策略组名称（可编辑）+ 操作按钮（运行新任务、编辑策略组、删除）
- 策略链路展示条
- 运行历史表格：
  - 列：# | 运行时间 | 日期范围 | 执行模式 | 最终结果 | 状态 | 操作
  - 点击某行 → 跳转到 `/backtest/group/:groupId/run/:runId`

### 第3层：步骤详情 (`/backtest/group/:groupId/run/:runId`)

- 顶部：返回按钮 + 运行信息（时间、日期范围）
- 步骤流程图（横向卡片）：
  - 每步：步骤编号 + 策略类型/频率标签 + 策略名 + 输入数量 + 输出数量
  - 步骤间：箭头 + 关联模式标签
  - 可点击「查看股票列表」展开中间结果（股票代码 + 匹配日期）
- 最终结果区域：
  - 选股类型：股票代码 + 匹配日期列表（表格形式：代码 | 匹配次数 | 匹配日期）
  - 回测类型：收益指标 + 权益曲线 + 交易记录（复用现有组件）

### 创建/编辑策略组 (`/backtest/group/create` 或 `/backtest/group/:groupId/edit`)

- 策略组名称输入
- 复用现有 PipelineBuilder 组件（选择策略 + 定义关联关系）
- 保存按钮

## 执行模式

运行策略组时可选两种模式：

### 一键执行

自动按顺序执行整条链路：
1. 第1步用全部股票（或指定范围）作为输入
2. 第N步用第N-1步的输出作为输入（关联模式）或用全量股票（独立模式）
3. 全部完成后返回最终结果

### 逐步执行

每步执行完暂停，展示中间结果：
1. 执行第1步 → 展示结果 → 用户确认「继续下一步」
2. 执行第2步 → 展示结果 → 用户确认
3. 直到所有步骤完成

逐步模式下，运行状态为 `step_N_done`，前端轮询状态并展示中间结果。

## 数据模型

### 新增表：strategy_groups

```sql
CREATE TABLE strategy_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pipeline TEXT NOT NULL,       -- JSON: [{filepath, class_name, frequency, params}]
    join_modes TEXT,              -- JSON: ["correlated", "independent", ...]
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 新增表：group_runs

```sql
CREATE TABLE group_runs (
    run_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    execution_mode TEXT NOT NULL, -- "auto" | "stepwise"
    status TEXT NOT NULL,         -- "running" | "step_N_done" | "success" | "failed"
    current_step INTEGER DEFAULT 0,
    steps_result TEXT,            -- JSON: [{step, input_count, output_count, symbols, task_id}]
    final_result TEXT,            -- JSON: 最终结果（同现有 backtest_tasks.result 格式）
    summary TEXT,                 -- JSON: {screened_count} 或 {total_return, max_drawdown}
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (group_id) REFERENCES strategy_groups(group_id)
);
```

### 现有表 backtest_tasks

保持不变，每个步骤的实际执行仍然创建 backtest_tasks 记录（复用现有引擎）。`group_runs.steps_result` 中引用对应的 `task_id`。

## API 设计

### 策略组 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backtest/groups` | 获取所有策略组（含最近运行摘要） |
| POST | `/api/backtest/groups` | 创建策略组 |
| GET | `/api/backtest/groups/:id` | 获取单个策略组详情 |
| PATCH | `/api/backtest/groups/:id` | 编辑（重命名/修改 pipeline） |
| DELETE | `/api/backtest/groups/:id` | 删除策略组（级联删除关联运行记录） |

### 运行相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/groups/:id/run` | 运行策略组（body: {start_date, end_date, execution_mode}） |
| GET | `/api/backtest/groups/:id/runs` | 获取运行历史列表 |
| GET | `/api/backtest/runs/:runId` | 获取运行详情（含各步骤结果） |
| GET | `/api/backtest/runs/:runId/status` | 获取运行状态（轮询用） |
| POST | `/api/backtest/runs/:runId/next-step` | 逐步模式下确认执行下一步 |

### 历史迁移

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/groups/migrate` | 扫描历史 source_task_id 链路，创建策略组并关联 |

## 执行引擎设计

### 一键执行流程

```
POST /api/backtest/groups/:id/run {start_date, end_date, execution_mode: "auto"}
```

后端：
1. 创建 group_run 记录，status="running"
2. 启动后台线程，按 pipeline 顺序依次执行：
   - 步骤N：根据 join_mode 确定输入（关联=上一步输出，独立=全量）
   - 调用现有 BacktestEngine 执行
   - 记录 input_count, output_count, symbols, task_id 到 steps_result
3. 全部完成 → status="success"，写入 final_result
4. 任一步骤失败 → status="failed"，写入 error

### 逐步执行流程

```
POST /api/backtest/groups/:id/run {execution_mode: "stepwise"}
```

后端：
1. 创建 group_run，status="running"，执行第1步
2. 第1步完成 → status="step_1_done"
3. 前端轮询发现 step_1_done，展示中间结果
4. 用户确认 → `POST /runs/:runId/next-step`
5. 后端执行下一步，重复直到全部完成

### 与现有系统的关系

- 每个步骤的实际执行复用现有 `BacktestEngine` + `task_manager`
- `group_runs.steps_result` 中的 `task_id` 指向 `backtest_tasks` 表
- 现有的 backtest 进度轮询机制保持不变（每步执行时可复用）

## 历史数据迁移逻辑

点击「迁移历史任务」触发：
1. 查询所有有 `source_task_id` 的任务
2. 构建链路树：找到所有根节点（无 source 的任务）
3. 对每条链路：
   - 从各任务的 `pipeline_info` 提取策略配置
   - 合并为完整 pipeline
   - 创建 strategy_group（默认命名："迁移-{日期}-#{N}"）
   - 创建 group_run，将链路上的任务结果填入 steps_result
4. 返回迁移数量

## 策略调试页

原 ScreenerPage 改造为「策略调试」页面：
- 保持现有功能：选择单个策略 → 配置参数 → 运行
- 结果存入 `backtest_tasks` 表（标记 task_type="debug"）
- 展示该页面下的调试历史任务列表
- 路由：`/debug`

## 错误处理

- 策略组中引用的策略文件不存在 → 运行前校验，返回明确错误
- 逐步模式下长时间未确认下一步 → 无超时限制，状态保持 step_N_done
- 运行中途服务重启 → status 保持 "running"/"step_N_done"，前端展示为中断状态，用户可重跑
