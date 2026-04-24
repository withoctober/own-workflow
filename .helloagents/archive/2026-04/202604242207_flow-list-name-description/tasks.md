# 任务清单: flow-list-name-description

```yaml
@feature: flow-list-name-description
@created: 2026-04-24
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 4 | 0 | 0 | 4 |

---

## 任务列表

### 1. Flow 返回结构

- [√] 1.1 在 `workflow/flow/registry.py` 中为每个 flow 增加中文 `name` 和 `description` 元数据 | depends_on: []
- [√] 1.2 让 `GET /api/flows` 返回扩展后的展示字段 | depends_on: [1.1]

### 2. 验证与文档

- [√] 2.1 更新 `tests/test_flows_registry.py` 与 `tests/test_app_routes.py`，覆盖 `name` 和 `description` | depends_on: [1.2]
- [√] 2.2 更新 `api.md`，补充 `GET /api/flows` 的最新返回示例 | depends_on: [2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-24 22:09 | 1.1 | completed | 已为各 flow 增加中文 `name` 和 `description` 元数据 |
| 2026-04-24 22:09 | 1.2 | completed | `/api/flows` 已返回展示字段与执行参数 schema |
| 2026-04-24 22:10 | 2.1 | completed | 已通过 `uv run python -m unittest tests.test_flows_registry tests.test_app_routes` 验证 |
| 2026-04-24 22:10 | 2.2 | completed | 已更新 `api.md` 的返回示例和字段说明 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

> 本任务只扩展 flow 展示元数据，不改变既有执行参数 schema 结构。
> 当前返回结构已同时包含 `id`、`name`、`description` 和 `run_request_schema`。
