# Soft Delete Backtest Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为回测任务列表增加软删除功能，已删除任务默认隐藏，前端可通过 checkbox 切换显示。

**Architecture:** 数据库新增 `deleted` 字段标识软删除；后端新增删除接口和 `show_deleted` 查询参数；前端任务列表每行增加删除按钮，顶部增加"显示已删除"checkbox，已删除任务灰色显示。

**Tech Stack:** Python/FastAPI backend, SQLite (via sqlite3), Vue 3 frontend

---

### Task 1: TaskManager 支持软删除

**Files:**
- Modify: `backend/services/backtest/task_manager.py`
- Test: `backend/tests/test_task_manager.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_task_manager.py`，内容如下：

```python
import pytest
from services.backtest.task_manager import TaskManager


@pytest.fixture
def tm(tmp_path):
    return TaskManager(db_path=str(tmp_path / "test.db"))


def test_delete_task_marks_deleted(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=True)
    match = next(t for t in tasks if t["task_id"] == task_id)
    assert match["deleted"] is True


def test_list_tasks_hides_deleted_by_default(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=False)
    assert all(t["task_id"] != task_id for t in tasks)


def test_list_tasks_shows_deleted_when_requested(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=True)
    assert any(t["task_id"] == task_id for t in tasks)


def test_delete_nonexistent_task_does_not_raise(tm):
    tm.delete_task("nonexistent")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_task_manager.py -x -q
```

预期：FAIL，`TaskManager` 缺少 `delete_task` 方法，`list_tasks` 缺少 `show_deleted` 参数。

- [ ] **Step 3: 修改 TaskManager**

在 `backend/services/backtest/task_manager.py` 中：

**3a. `_init_table` 的 ALTER TABLE 循环中补充 `deleted` 列：**

```python
for col, typedef in [
    ("task_type", "TEXT NOT NULL DEFAULT 'screener'"),
    ("summary", "TEXT"),
    ("pipeline_info", "TEXT"),
    ("start_date", "TEXT"),
    ("end_date", "TEXT"),
    ("source_task_id", "TEXT"),
    ("deleted", "INTEGER NOT NULL DEFAULT 0"),
]:
```

**3b. 新增 `delete_task` 方法（在 `fail_task` 之后）：**

```python
def delete_task(self, task_id: str):
    conn = self._get_conn()
    try:
        conn.execute(
            "UPDATE backtest_tasks SET deleted = 1 WHERE task_id = ?",
            (task_id,),
        )
        conn.commit()
    finally:
        conn.close()
```

**3c. 修改 `list_tasks` 签名和查询：**

```python
def list_tasks(self, show_deleted: bool = False) -> list[dict]:
    conn = self._get_conn()
    try:
        if show_deleted:
            rows = conn.execute(
                "SELECT task_id, status, task_type, summary, created_at, source_task_id, deleted FROM backtest_tasks ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT task_id, status, task_type, summary, created_at, source_task_id, deleted FROM backtest_tasks WHERE deleted = 0 ORDER BY created_at DESC"
            ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        item = {
            "task_id": r["task_id"],
            "status": r["status"],
            "task_type": r["task_type"],
            "created_at": r["created_at"],
            "deleted": bool(r["deleted"]),
        }
        if r["source_task_id"]:
            item["source_task_id"] = r["source_task_id"]
        if r["summary"]:
            try:
                item["summary"] = json.loads(r["summary"])
            except Exception:
                pass
        result.append(item)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_task_manager.py -x -q
```

预期：4 passed

- [ ] **Step 5: 全量测试确认无回归**

```bash
python -m pytest backend/tests/ -x -q
```

预期：全部通过

- [ ] **Step 6: 提交**

```bash
git add backend/services/backtest/task_manager.py backend/tests/test_task_manager.py
git commit -m "feat: soft delete for backtest tasks in TaskManager"
```

---

### Task 2: 后端路由支持软删除接口

**Files:**
- Modify: `backend/routers/backtest.py`
- Test: `backend/tests/test_backtest_api.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_backtest_api.py` 末尾追加：

```python
class TestSoftDelete:
    def test_delete_task(self, client, tmp_task_manager):
        task_id = tmp_task_manager.create_task(task_type="screener")
        resp = client.delete(f"/api/backtest/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_task_hidden_by_default(self, client, tmp_task_manager):
        task_id = tmp_task_manager.create_task(task_type="screener")
        tmp_task_manager.delete_task(task_id)
        resp = client.get("/api/backtest/tasks")
        ids = [t["task_id"] for t in resp.json()]
        assert task_id not in ids

    def test_deleted_task_visible_with_show_deleted(self, client, tmp_task_manager):
        task_id = tmp_task_manager.create_task(task_type="screener")
        tmp_task_manager.delete_task(task_id)
        resp = client.get("/api/backtest/tasks?show_deleted=true")
        ids = [t["task_id"] for t in resp.json()]
        assert task_id in ids

    def test_deleted_task_has_deleted_flag(self, client, tmp_task_manager):
        task_id = tmp_task_manager.create_task(task_type="screener")
        tmp_task_manager.delete_task(task_id)
        resp = client.get(f"/api/backtest/tasks?show_deleted=true")
        match = next(t for t in resp.json() if t["task_id"] == task_id)
        assert match["deleted"] is True
```

先查看 `test_backtest_api.py` 中 `client` 和 `tmp_task_manager` fixture 的定义，确认可以复用。

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_backtest_api.py::TestSoftDelete -x -q
```

预期：FAIL，`DELETE /api/backtest/tasks/{task_id}` 路由不存在，`list_tasks` 不接受 `show_deleted` 参数。

- [ ] **Step 3: 修改路由**

在 `backend/routers/backtest.py` 中：

**3a. 修改 `api_list_tasks`，增加 `show_deleted` 查询参数：**

```python
@router.get("/tasks")
def api_list_tasks(show_deleted: bool = False):
    return task_manager.list_tasks(show_deleted=show_deleted)
```

**3b. 新增删除路由（在 `api_list_tasks` 之后）：**

```python
@router.delete("/tasks/{task_id}")
def api_delete_task(task_id: str):
    task_manager.delete_task(task_id)
    return {"ok": True}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_backtest_api.py::TestSoftDelete -x -q
```

预期：4 passed

- [ ] **Step 5: 全量测试确认无回归**

```bash
python -m pytest backend/tests/ -x -q
```

预期：全部通过

- [ ] **Step 6: 提交**

```bash
git add backend/routers/backtest.py backend/tests/test_backtest_api.py
git commit -m "feat: add DELETE /api/backtest/tasks/{task_id} and show_deleted query param"
```

---

### Task 3: 前端 BacktestPage 增加删除按钮和 checkbox

**Files:**
- Modify: `frontend/src/views/BacktestPage.vue`
- Modify: `frontend/src/api/index.js`

- [ ] **Step 1: 在 `api/index.js` 新增删除接口**

找到 `fetchBacktestTasks` 等函数所在位置，追加：

```js
export function deleteBacktestTask(taskId) {
  return axios.delete(`/api/backtest/tasks/${taskId}`)
}

export function fetchBacktestTasks(showDeleted = false) {
  return axios.get(`/api/backtest/tasks${showDeleted ? '?show_deleted=true' : ''}`)
}
```

注意：如果 `fetchBacktestTasks` 已存在则直接替换，增加 `showDeleted` 参数。

- [ ] **Step 2: 修改 BacktestPage.vue — script 部分**

**2a. 导入 `deleteBacktestTask`：**

```js
import { fetchBacktestTasks, deleteBacktestTask, ... } from '../api'
```

**2b. 新增响应式变量：**

```js
const showDeleted = ref(false)
```

**2c. 修改 `loadTasks` 使用 `showDeleted`：**

```js
async function loadTasks() {
  const { data } = await fetchBacktestTasks(showDeleted.value)
  tasks.value = data
}
```

**2d. 新增删除函数：**

```js
async function onDeleteTask(taskId) {
  await deleteBacktestTask(taskId)
  await loadTasks()
}
```

**2e. 监听 `showDeleted` 变化重新加载：**

```js
import { ref, onMounted, watch } from 'vue'

watch(showDeleted, () => loadTasks())
```

- [ ] **Step 3: 修改 BacktestPage.vue — template 部分**

**3a. 在任务列表标题行新增 checkbox（放在任务历史 `<h3>` 同行）：**

```html
<div class="task-list-header">
  <h3>任务历史</h3>
  <label class="show-deleted-label">
    <input type="checkbox" v-model="showDeleted" />
    显示已删除的任务
  </label>
</div>
```

**3b. 在任务表格操作列新增删除按钮（与"查看结果"按钮同列）：**

```html
<td>
  <button @click="$router.push('/backtest/result/' + t.task_id)">查看结果</button>
  <button class="btn-delete" @click="onDeleteTask(t.task_id)" :disabled="t.deleted">删除</button>
</td>
```

**3c. 已删除任务行加灰色样式：**

```html
<tr v-for="t in tasks" :key="t.task_id" :class="{ 'row-deleted': t.deleted }">
```

- [ ] **Step 4: 修改 BacktestPage.vue — style 部分**

追加样式：

```css
.task-list-header { display: flex; align-items: center; gap: 16px; margin-bottom: 8px; }
.task-list-header h3 { margin: 0; }
.show-deleted-label { font-size: 13px; color: #606266; display: flex; align-items: center; gap: 6px; cursor: pointer; }
.btn-delete { background: #f56c6c; color: white; border: none; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; margin-left: 6px; }
.btn-delete:disabled { background: #dcdfe6; color: #909399; cursor: not-allowed; }
.row-deleted td { color: #c0c4cc; text-decoration: line-through; }
```

- [ ] **Step 5: 验证前端**

启动前端开发服务器，访问 `http://localhost:3001/backtest`：
- 确认每行有「删除」按钮
- 点击删除后任务消失
- 勾选「显示已删除的任务」后任务以灰色删除线重新出现
- 被删除任务的「删除」按钮变灰不可点击

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/BacktestPage.vue frontend/src/api/index.js
git commit -m "feat: add soft delete button and show-deleted toggle in BacktestPage"
```
