# 模块索引

- `app`: FastAPI 路由、依赖注入、统一响应包装与全局异常处理
- `runtime`: GraphRuntime、运行上下文、状态持久化与结构化执行事件日志
- `flows`: 业务流程定义、节点公共 helper 与节点内部关键步骤日志
- `llm`: 通用模型调用与 prompt 渲染
- `integrations`: 外部接口适配，包含共享飞书与热点集成能力
- `stores`: 数据后端与装配

## 本次更新

- `runtime`：补充基于 `events.jsonl` 的节点内部结构化日志能力
- `flows`：为 `content_collect`、`content_create`、`daily_report` 接入关键子步骤执行日志
