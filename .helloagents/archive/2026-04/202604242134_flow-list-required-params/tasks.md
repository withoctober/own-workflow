# 任务清单: flow-list-required-params

```yaml
@feature: flow-list-required-params
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

### 1. Flow 元数据与接口

- [√] 1.1 在 `workflow/flow/registry.py` 中为工作流注册表增加 `run_request_schema` 元数据，并保持现有构建接口兼容 | depends_on: []
- [√] 1.2 让 `GET /api/flows` 返回扩展后的工作流列表结构 | depends_on: [1.1]

### 2. 验证与文档

- [√] 2.1 更新 `tests/test_flows_registry.py` 与 `tests/test_app_routes.py`，覆盖 `run_request_schema` 返回值 | depends_on: [1.2]
- [√] 2.2 更新 `README.md`、`api.md` 与知识库文档，说明列表接口新增的 `run_request_schema` 字段 | depends_on: [2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-24 21:39 | 1.1 | completed | 已将工作流注册表升级为 builder + run_request_schema 元数据 |
| 2026-04-24 21:39 | 1.2 | completed | `/api/flows` 已返回每个 flow 的完整运行参数 schema |
| 2026-04-24 21:40 | 2.1 | completed | 已通过 `uv run python -m unittest tests.test_flows_registry` 与 `uv run --extra dev python -m unittest tests.test_app_routes` 验证 |
| 2026-04-24 21:41 | 2.2 | completed | 已同步 README、api.md 与知识库模块文档 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

> 本任务按最新需求返回完整运行参数 schema，并在字段级和 schema 级同时标记必填状态。
> 验证结果：`content-create-rewrite` 的 `source_url` 被标记为必填，其余 flow 只暴露实际可用的可选参数。
