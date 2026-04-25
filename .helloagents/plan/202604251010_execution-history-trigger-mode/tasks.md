# 任务清单: execution-history-trigger-mode

```yaml
@feature: execution-history-trigger-mode
@created: 2026-04-25
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 4 | 0 | 0 | 4 |

### LIVE_STATUS

```yaml
status: in_progress
status: completed
completed: 4
failed: 0
pending: 0
total: 4
done: 4
percent: 100
current: 已完成 trigger_mode 全链路改造
updated_at: 2026-04-25 10:29:00 +0800
```

---

## 任务列表

### 1. 运行链路与数据模型

- [√] 1.1 为 `RunRequest`、`RuntimeContext`、`StateRepository` 增加 `trigger_mode`，确保手动、cron、resume 三条路径都能正确落盘 | depends_on: []
- [√] 1.2 扩展 `workflow_runs` 表结构、`WorkflowRun` 模型和 `model.run` 读写逻辑，持久化 `trigger_mode` | depends_on: [1.1]

### 2. API 与测试文档

- [√] 2.1 扩展 `/api/runs` 与 run 详情响应，返回 `trigger_mode`，并更新路由相关测试 | depends_on: [1.2]
- [√] 2.2 更新 README、`api.md`、知识库模块文档和 CHANGELOG，说明执行历史新增触发方式字段 | depends_on: [2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-25 10:10:41 +0800 | 方案创建 | completed | 已创建 implementation 方案包 |
| 2026-04-25 10:10:41 +0800 | 方案填充 | completed | 明确 manual/cron 与 resume 沿用策略 |
| 2026-04-25 10:29:00 +0800 | 开发实施 | completed | 已完成 runtime/model/app/test/doc 全链路改造 |
| 2026-04-25 10:29:00 +0800 | 验证 | warning | `compileall` 通过；自动化测试因环境缺少 fastapi/langgraph/langchain_core/pytest 未能完整执行 |

---

## 执行备注

> 本次只补充 `manual` 与 `cron` 两种触发方式；未来若需要区分 `resume`、`api`、`webhook` 等来源，可在同一字段上扩展枚举值。
