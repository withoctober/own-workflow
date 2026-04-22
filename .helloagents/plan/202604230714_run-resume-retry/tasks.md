# 任务清单: run-resume-retry

```yaml
@feature: run-resume-retry
@created: 2026-04-23
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 6 | 0 | 0 | 6 |

---

## 任务列表

### 1. 恢复能力实现

- [√] 1.1 在 `workflow/runtime/persistence.py` 中新增 run 恢复前的状态校验与清理逻辑 | depends_on: []
- [√] 1.2 在 `workflow/runtime/engine.py` 中新增 `resume` 入口与 completed 节点跳过逻辑 | depends_on: [1.1]

### 2. API 暴露

- [√] 2.1 在 `app/routes.py` 中新增 `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume` 接口 | depends_on: [1.2]

### 3. 验证与同步

- [√] 3.1 在 `tests/test_runtime_smoke.py` 中补充 resume 行为测试 | depends_on: [1.2]
- [√] 3.2 在 `tests/test_app_routes.py` 中补充 resume 路由测试 | depends_on: [2.1]
- [√] 3.3 更新 README 和知识库模块文档、CHANGELOG | depends_on: [3.1, 3.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-23 07:14 | 方案创建 | completed | 已确认采用显式恢复模式，沿用原 batch_id 恢复失败 run |
| 2026-04-23 07:17 | 1.1 / 1.2 / 2.1 | completed | 已实现 runtime resume、失败态清理和独立恢复接口 |
| 2026-04-23 07:18 | 3.1 / 3.2 | completed | 已补充 runtime 与路由测试，验证已完成节点不会重复执行 |
| 2026-04-23 07:19 | 3.3 | completed | 已同步 README、知识库模块文档与 CHANGELOG |

---

## 执行备注

- 本次 `resume` 只覆盖显式失败重试，不扩展自动重试策略。
- “从失败节点开始”按运行语义实现为：已完成节点跳过，失败节点重新执行。
