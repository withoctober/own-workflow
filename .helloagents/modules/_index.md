# 模块索引

- `app`: FastAPI 路由、依赖注入、统一响应包装与全局异常处理
- `runtime`: GraphRuntime、运行上下文、状态持久化与结构化执行事件日志
- `flows`: 业务流程定义、节点公共 helper 与节点内部关键步骤日志
- `core`: 通用模型调用、环境变量读取与 prompt 渲染
- `integrations`: 外部接口适配，包含共享飞书与热点集成能力
- `store`: 数据后端与装配
- `delivery`: 容器镜像构建与 GitHub Actions 发布流程

## 本次更新

- `runtime`：补充基于 `events.jsonl` 的节点内部结构化日志能力
- `flows`：为 `content_collect`、`content_create`、`daily_report` 接入关键子步骤执行日志
- `runtime`：新增 `scripts/run_flow_once.py`，支持不经 HTTP 服务直接触发单次租户工作流执行
- `delivery`：新增根目录 `Dockerfile` 和 GitHub Actions 镜像构建推送流程
