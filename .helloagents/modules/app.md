# 模块: app

## 职责

- 提供 FastAPI 应用初始化与路由注册。
- 处理 HTTP 层的依赖注入、请求入口与响应输出。
- 统一 API 返回结构为 `code/message/data`。
- 通过全局异常处理器将业务异常、参数校验异常和兜底异常转换为统一 JSON 响应。
- 通过 `app.model` 访问租户与租户飞书配置数据，通过 `workflow.integrations` 调用共享飞书集成能力。
- 提供 `POST /tenants` 入口，支持仅传 `tenant_name` 创建租户并由服务端自动生成唯一 `tenant_id`。
- 提供租户工作流 schedule 的查询、创建更新、删除和手动触发入口，并在应用生命周期中启动后台调度器。
- 提供失败 run 的显式恢复入口，允许外部系统对指定 `batch_id` 进行重试。

## 行为规范

- 所有接口成功响应都返回 HTTP 200，且响应体格式为 `{"code": 0, "message": "ok", "data": ...}`。
- 所有接口失败响应都返回 HTTP 200，且由 `code` 字段表达业务或系统错误码。
- 路由层优先抛出 `HTTPException` 表达明确业务错误，再由应用层异常处理器统一包装。
- 参数校验错误由 FastAPI 触发 `RequestValidationError`，最终同样返回统一响应格式。
- 新增租户时优先使用 `POST /tenants`，由 `app.model.generate_tenant_id()` 基于 `tenant_name` 自动生成唯一业务标识。
- 兼容保留 `PUT /tenants/{tenant_id}`，用于显式指定 `tenant_id` 的更新或初始化场景。
- `PUT /tenants/{tenant_id}/schedules/{flow_id}` 负责写入或更新单条租户工作流 schedule，并保持每个租户每个工作流只有 1 条配置。
- `GET /tenants/{tenant_id}/schedules/{flow_id}` 用于读取单个租户单个工作流的 schedule 详情。
- `POST /tenants/{tenant_id}/schedules/{flow_id}/trigger` 用于手动复用 schedule 配置触发工作流执行，便于调试与验收。
- `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume` 用于恢复 `failed/blocked` 的指定 run，复用原运行目录与上下文配置。

## 依赖关系

- 依赖 `app.schemas` 提供响应模型和辅助构造函数。
- 依赖 `app.model` 提供租户与租户飞书配置的数据访问逻辑。
- 依赖 `workflow.integrations.feishu` 提供飞书链接解析、远程校验和配置构建能力。
- 依赖 `workflow.runtime.engine` 提供流程运行入口。
- 依赖 `workflow.runtime.scheduler` 提供 cron 校验、下次执行时间计算和后台调度器生命周期接入。
