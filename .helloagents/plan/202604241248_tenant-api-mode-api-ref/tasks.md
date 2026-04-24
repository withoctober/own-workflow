# 任务清单: tenant-api-mode-api-ref

```yaml
@feature: tenant-api-mode-api-ref
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

### 1. 租户持久化与接口

- [√] 1.1 在 `model/db.py`、`model/types.py`、`model/tenant.py` 中增加 `api_mode/api_ref` 持久化与运行时注入 | depends_on: []
- [√] 1.2 在 `app/schemas.py`、`app/routes.py` 中扩展租户接口入参与返回结构 | depends_on: [1.1]

### 2. 运行时配置接入

- [√] 2.1 在 `workflow/runtime/tenant.py`、`workflow/core/ai.py`、`workflow/integrations/hotspots.py`、`workflow/flow/content_create/*` 中接入 `api_mode/api_ref` 解析与使用 | depends_on: [1.1]
- [√] 2.2 更新 `tests/` 与 `README.md`，验证 system/custom 两种模式的兼容性 | depends_on: [1.2, 2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-24 12:48 | 方案包创建 | completed | 已创建 implementation 方案包 |
| 2026-04-24 13:02 | 方案设计 | completed | 确认采用 `api_mode + api_ref(JSON)` 方案 |
| 2026-04-24 12:56 | 开发实施 | completed | 已完成租户数据模型、运行时注入、文档与测试更新 |
| 2026-04-24 12:56 | 测试验证 | completed | `uv run python -m unittest tests.test_app_model tests.test_app_routes tests.test_workflow_ai_config tests.test_runtime_smoke tests.test_runtime_scheduler` 通过 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等
- 用户确认：仅 `api_mode=custom` 时存储并使用 `api_ref`
- `api_ref` 的内部键名采用 `OPENAI_API_KEY`、`TIKHUB_API_KEY`、`ARK_API_KEY` 这类环境变量风格命名
