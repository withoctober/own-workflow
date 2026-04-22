# 任务清单: workflow-node-logging-rollout

```yaml
@feature: workflow-node-logging-rollout
@created: 2026-04-22
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 7 | 0 | 0 | 7 |

---

## 任务列表

### 1. 公共层设计与实现

- [√] 1.1 在 `workflow/flow/common.py` 中实现统一节点日志与工件 helper | depends_on: []
- [√] 1.2 在 `workflow/flow/common.py` 中实现失败现场快照和统一命名约定 | depends_on: [1.1]

### 2. 工作流接入

- [√] 2.1 在 `workflow/flow/content_create/nodes.py` 中接入公共日志 helper | depends_on: [1.2]
- [√] 2.2 在 `workflow/flow/daily_report/nodes.py` 中接入公共日志 helper | depends_on: [1.2]
- [√] 2.3 在 `workflow/flow/content_collect/nodes.py` 中接入公共日志 helper | depends_on: [1.2]

### 3. 验证

- [√] 3.1 在 `tests/` 中补充公共日志与失败现场相关测试 | depends_on: [2.1, 2.2, 2.3]
- [√] 3.2 运行相关测试并检查日志产物行为 | depends_on: [3.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-22 23:29 | 方案创建 | completed | 已创建 implementation 方案包并确认采用公共层抽象 |
| 2026-04-22 23:33 | 1.1 / 1.2 | completed | 公共层新增统一快照和失败现场 helper |
| 2026-04-22 23:37 | 2.1 | completed | `content_create` 已接入阶段快照与失败现场工件 |
| 2026-04-22 23:38 | 2.2 | completed | `daily_report` 已接入阶段快照与失败现场工件 |
| 2026-04-22 23:42 | 2.3 | completed | `content_collect` 已接入关键阶段快照与失败现场工件 |
| 2026-04-22 23:44 | 3.1 / 3.2 | completed | 新增 helper 单测，并用 `uv run python -m unittest` 验证通过 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

- 本次任务以“统一日志能力”优先，暂不同时引入节点内部自动重试机制，避免两个改动面耦合。
- 工件策略优先覆盖关键阶段和失败现场，不追求把所有中间变量都写盘。
