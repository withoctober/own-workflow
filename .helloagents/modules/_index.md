# 模块索引

- `app`: FastAPI 路由、依赖注入、统一响应包装与全局异常处理
- `runtime`: GraphRuntime、运行上下文、状态持久化与结构化执行事件日志
- `flows`: 业务流程定义、节点公共 helper 与节点内部关键步骤日志
- `core`: 通用模型调用、环境变量读取与 prompt 渲染
- `integrations`: 外部接口适配，包含共享飞书与热点集成能力
- `store`: 数据后端与装配
- `delivery`: 容器镜像构建、Compose 本地运行与 GitHub Actions 发布流程

## 本次更新

- `runtime`：补充基于 `events.jsonl` 的节点内部结构化日志能力
- `flows`：为 `content_collect`、`content_create`、`daily_report` 接入关键子步骤执行日志
- `runtime`：新增 `scripts/run_flow_once.py`，支持不经 HTTP 服务直接触发单次租户工作流执行
- `delivery`：新增根目录 `Dockerfile` 和 GitHub Actions 镜像构建推送流程
- `delivery`：新增根目录 `docker-compose.yml`，支持直接拉取已发布镜像并复用 `.env` 启动应用服务
- `app`：新增租户级 `X-API-Key` 鉴权与基于 API key 的租户反查，业务接口默认可只传 API key
- `app`：新增 artifact 业务产物列表与详情接口，支持按当前租户查询创作完成内容
- `flows`：`content_create` 在写入生成作品库的同时，同步把最终结果写入独立 `artifacts` 业务表
- `runtime`：已用真实数据库和 `content-create-original` 流程验证 `artifacts` 表同步与落库链路，批次 `20260424161200` 成功写入 artifact 记录
- `app`：`GET /api/flows` 新增 `run_request_schema` 返回结构，前端可直接读取字段定义与必填状态
- `flows`：工作流注册表开始集中维护每个 flow 的运行参数 schema，覆盖 `tenant_id`、`batch_id` 与按 flow 差异化的 `source_url`
- `app`：`GET /api/flows` 进一步补充中文 `name` 与 `description`，前端可直接展示工作流名称和用途说明
- `flows`：工作流注册表开始集中维护每个 flow 的中文展示元数据，与执行参数 schema 一起返回
- `integrations`：图片生成配置统一改为 `IMAGE_PROVIDER` 与 `IMAGE_API_*`，同时支持租户 `api_ref` 和系统环境变量
- `integrations`：移除 `blt` 图片 provider，当前图片 provider 保留 `ark` 与 `openai`
- `flows`：`content_create` 图片生成节点移除 provider/model 硬编码，统一使用图片集成层配置解析
- `app`：租户 `api_mode=custom` 校验改为要求新的图片配置键
