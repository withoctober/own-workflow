# 模块: app

## 职责

- 提供 FastAPI 应用初始化与路由注册。
- 处理 HTTP 层的依赖注入、请求入口与响应输出。
- 统一 API 返回结构为 `code/message/data`。
- 通过全局异常处理器将业务异常、路由未匹配、参数校验异常和兜底异常转换为统一 JSON 响应。
- 通过顶层 `model` 包访问租户、运行配置、调度配置和表格数据。
- 所有公开业务路由统一挂载在 `/api` 前缀下。
- 提供 `POST /api/tenants` 入口，支持仅传 `tenant_name` 创建租户并由服务端自动生成唯一 `tenant_id`。
- 提供租户级 `api_mode` 与 `api_ref` 配置入口，支持区分系统默认 API 配置与租户自定义 API 配置。
- 提供当前租户表格数据集的列表、查询、新增、更新和软删除入口。
- 提供租户工作流 schedule 的查询、创建更新、删除和手动触发入口，并在应用生命周期中启动后台调度器。
- 提供失败 run 的显式恢复入口，允许外部系统对指定 `batch_id` 进行重试。
- 提供租户级 `X-API-Key` 鉴权能力，保护除 `/api/health` 与租户创建/列表外的业务接口，并支持仅通过 API key 反查当前租户。
- 提供 `GET /api/artifacts` 与 `GET /api/artifacts/{artifact_id}` 入口，用于读取当前租户已完成创作内容的业务产物列表与详情。
- 提供 `GET /api/flows` 入口，并为每个工作流返回中文 `name`、中文 `description` 和 `run_request_schema`，描述工作流展示信息及执行参数要求。

## 行为规范

- 所有接口成功响应都返回 HTTP 200，且响应体格式为 `{"code": 0, "message": "ok", "data": ...}`。
- 所有接口失败响应都返回 HTTP 200，且由 `code` 字段表达业务或系统错误码。
- 路由层优先抛出 `HTTPException` 表达明确业务错误，再由应用层异常处理器统一包装。
- Starlette 404 等框架层异常同样由应用层包装为统一响应，避免未注册路径直接返回原生错误结构。
- 参数校验错误由 FastAPI 触发 `RequestValidationError`，最终同样返回统一响应格式。
- 新增租户时使用 `POST /api/tenants`，由 `model.generate_tenant_id()` 基于 `tenant_name` 自动生成唯一业务标识。
- 租户创建接口支持 `api_mode=system|custom`；当 `api_mode=custom` 时可写入 `api_ref` JSON，内部键名采用 `OPENAI_API_KEY`、`TIKHUB_API_KEY`、`ARK_API_KEY` 这类环境变量风格命名。
- 路径中不再暴露 `tenant_id`，当前租户统一由 `X-API-Key` 反查获得。
- `GET /api/tables`、`GET /api/tables/{dataset_key}`、`POST /api/tables/{dataset_key}`、`PUT /api/tables/{dataset_key}/{record_id}`、`DELETE /api/tables/{dataset_key}/{record_id}` 提供当前租户表格数据操作。
- `GET /api/artifacts` 支持按当前租户读取 artifact 列表，并可使用 `flow_id/limit/offset` 过滤分页。
- `GET /api/artifacts/{artifact_id}` 返回当前租户单个 artifact 的完整详情。
- `GET /api/flows` 返回的每个 flow 条目除 `id` 外，还包含 `name`、`description` 和 `run_request_schema`；前两者可直接用于前端展示，schema 使用 `type/properties/required` 结构，并在字段级补充 `required` 标记，便于前端直接生成执行表单。
- `GET /api/schedules`、`GET /api/schedules/{flow_id}`、`PUT /api/schedules/{flow_id}`、`DELETE /api/schedules/{flow_id}`、`POST /api/schedules/{flow_id}/trigger` 提供当前租户工作流 schedule 操作。
- `POST /api/flows/{flow_id}/runs` 采用 RESTful 创建语义，接口会立即创建 run 资源并返回 `batch_id/run_path`，后续通过 `GET /api/flows/{flow_id}/runs/{batch_id}` 查询状态。
- `POST /api/flows/{flow_id}/runs/{batch_id}/resume` 用于恢复当前租户 `failed/blocked` 的指定 run，复用原运行目录与上下文配置。
- 受保护接口统一从请求头读取 `X-API-Key`，服务端先通过 API key 反查当前租户，再执行后续业务逻辑。
- 个别请求体若传入可选 `tenant_id`，该值必须与 `X-API-Key` 绑定的租户一致，否则返回 403。

## 依赖关系

- 依赖 `app.schemas` 提供响应模型和辅助构造函数。
- 依赖顶层 `model` 包提供租户、调度、运行配置和 store 数据访问逻辑。
- 依赖顶层 `model` 包新增的 `artifacts` CRUD 能力读取业务产物。
- 依赖 `workflow.store.database` 提供表格数据集定义。
- 依赖 `workflow.runtime.engine` 提供流程运行入口。
- 依赖 `workflow.flow.registry` 提供工作流列表及其 `run_request_schema` 元数据。
- 依赖 `workflow.runtime.scheduler` 提供 cron 校验、下次执行时间计算和后台调度器生命周期接入。
