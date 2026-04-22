# 模块: runtime

## 职责

- 提供 `GraphRuntime` 作为工作流运行入口。
- 构建单次 run 的 `RuntimeContext`，统一暴露运行目录、工件目录、状态文件和事件日志文件。
- 通过 `StateRepository` 管理 `state.json`、checkpoint 和 `events.jsonl`。
- 在 run/node 边界事件之外，提供节点内部结构化执行日志写入能力，支持记录子步骤、耗时、异常和摘要信息。

## 行为规范

- 每次 run 都会在 `var/runs/{tenant_id}/{flow_id}/{batch_id}/` 下生成运行产物。
- `state.json` 保存当前运行状态、节点状态、输出、消息与错误信息。
- `events.jsonl` 追加记录运行事件，既包含 `run_started`、`node_started`、`node_finished`、`run_finished` 等边界事件，也包含 `node_step` 类型的节点内部步骤事件。
- 节点内部日志统一通过 `RuntimeContext.log_node_event(...)` 或 flow 公共 helper 间接写入，避免节点直接拼接原始事件结构。
- 内部步骤事件至少包含 `event`、`node_id`、`step_id`、`message`，按需包含 `detail`、`duration_ms` 和 `level`。

## 依赖关系

- 依赖 `workflow.settings` 提供运行目录配置。
- 依赖 `workflow.jsonfile` 读写状态文件。
- 依赖 `langgraph` 的状态图与 checkpoint 机制执行图流程。
- 被 `workflow.flow.*` 节点通过 `RuntimeContext` 间接调用，用于结构化日志落盘。
