# 模块: runtime

## 职责

- 提供 `GraphRuntime` 作为工作流运行入口。
- 构建单次 run 的 `RuntimeContext`，统一暴露运行目录、工件目录、状态文件和事件日志文件。
- 通过 `StateRepository` 管理 `state.json`、checkpoint 和 `events.jsonl`。
- 在 run/node 边界事件之外，提供节点内部结构化执行日志写入能力，支持记录子步骤、耗时、异常和摘要信息。
- 提供 `TenantFlowScheduler`，基于数据库中的租户工作流 schedule 记录执行后台轮询调度。
- 提供项目级一次性触发脚本 `scripts/run_flow_once.py`，可直接复用本地 `.env` 与租户运行配置执行单次工作流。

## 行为规范

- 每次 run 都会在 `var/runs/{tenant_id}/{flow_id}/{batch_id}/` 下生成运行产物。
- `state.json` 保存当前运行状态、节点状态、输出、消息与错误信息。
- `events.jsonl` 追加记录运行事件，既包含 `run_started`、`node_started`、`node_finished`、`run_finished` 等边界事件，也包含 `node_step` 类型的节点内部步骤事件。
- 对 `failed` 或 `blocked` 的 run，可通过显式 `resume` 路径沿用原 `batch_id` 继续执行；恢复时已记录在 `completed_nodes` 中的节点会被跳过，失败节点会清理旧错误态后重试，并在恢复前移除无关的失败/阻塞/运行中残留节点状态。
- `resume` 成功完成后，最终 `state.json` 以本次运行得到的 `messages/errors` 为准，不会把恢复前已有消息再次重复追加到完成态。
- 节点内部日志统一通过 `RuntimeContext.log_node_event(...)` 或 flow 公共 helper 间接写入，避免节点直接拼接原始事件结构。
- 内部步骤事件至少包含 `event`、`node_id`、`step_id`、`message`，按需包含 `detail`、`duration_ms` 和 `level`。
- 调度器通过 `tenant_flow_schedules` 表恢复激活中的 schedule，按 cron 计算 `next_run_at`，到期后复用 `GraphRuntime.run(...)` 执行工作流。
- 调度执行完成后，调度器负责回写 `last_run_at`、`last_status`、`last_error`、`last_batch_id` 和新的 `next_run_at`。
- `scripts/run_flow_once.py` 不依赖 HTTP 服务，只要本地 `.env` 可读取并且 PostgreSQL 中存在对应租户的飞书配置，即可直接执行一次工作流。
- `TenantRuntimeConfig` 会携带租户级 `api_mode`、`api_ref` 与默认模型配置，并在工作流运行前一次性注入；节点执行期间不再额外回查数据库。

## 依赖关系

- 依赖 `workflow.settings` 提供运行目录配置。
- 依赖 `workflow.jsonfile` 读写状态文件。
- 依赖 `langgraph` 的状态图与 checkpoint 机制执行图流程。
- 被 `workflow.flow.*` 节点通过 `RuntimeContext` 间接调用，用于结构化日志落盘。
- 依赖 `app.model` 读写 schedule 元数据、锁状态和运行结果。
