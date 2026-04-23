# API 文档

本文档面向接口调用方，说明当前服务的鉴权方式、统一返回结构，以及所有 RESTful API 的调用方法。

## 基础信息

- Base URL: `http://<host>:<port>`
- Content-Type: `application/json`
- 鉴权头: `X-API-Key`

示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/flows"
```

## 统一返回结构

所有接口无论成功或失败，HTTP 状态码都返回 `200`，通过响应体中的 `code` 表示业务结果。

成功示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

失败示例：

```json
{
  "code": 401,
  "message": "X-API-Key 无效",
  "data": ""
}
```

常见业务码：

- `0`: 成功
- `400`: 请求参数或依赖配置错误
- `401`: 未鉴权或 API key 无效
- `403`: API key 与显式 `tenant_id` 不匹配
- `404`: 资源不存在
- `422`: 请求体验证失败
- `500`: 服务内部错误
- `503`: 下游依赖暂不可用

## 鉴权规则

### 免鉴权接口

- `GET /health`
- `GET /tenants`
- `POST /tenants`

### 受保护接口

其余接口都需要通过请求头传 `X-API-Key`。

当前服务会优先根据 `X-API-Key` 反查租户，因此调用推荐接口时，默认不需要再显式传 `tenant_id`。

如果你继续调用兼容保留的老接口，例如：

- `/tenants/{tenant_id}/...`
- `/flows/{flow_id}/runs/{tenant_id}/{batch_id}`

那么路径中的 `tenant_id` 必须和 `X-API-Key` 绑定的租户一致，否则会返回：

```json
{
  "code": 403,
  "message": "X-API-Key 与 tenant_id 不匹配",
  "data": ""
}
```

## 推荐调用路径

建议优先使用以下不显式携带 `tenant_id` 的路径：

- `GET /flows`
- `POST /flows/{flow_id}/runs`
- `GET /flows/{flow_id}/runs/{batch_id}`
- `POST /flows/{flow_id}/runs/{batch_id}/resume`
- `GET /tenant/feishu`
- `PUT /tenant/feishu`
- `GET /tenant/schedules`
- `GET /tenant/schedules/{flow_id}`
- `PUT /tenant/schedules/{flow_id}`
- `DELETE /tenant/schedules/{flow_id}`
- `POST /tenant/schedules/{flow_id}/trigger`

## 租户接口

### 1. 健康检查

`GET /health`

用途：
- 检查服务是否存活

请求示例：

```bash
curl "http://127.0.0.1:8000/health"
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "ok"
  }
}
```

### 2. 获取租户列表

`GET /tenants`

用途：
- 获取当前所有租户

请求示例：

```bash
curl "http://127.0.0.1:8000/tenants"
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tenants": [
      {
        "tenant_id": "default",
        "tenant_name": "默认租户",
        "api_key": "",
        "is_active": true,
        "default_llm_model": "",
        "timeout_seconds": 30,
        "max_retries": 2
      }
    ]
  }
}
```

### 3. 创建租户

`POST /tenants`

用途：
- 新建租户
- 服务端会根据 `tenant_name` 自动生成唯一的 `tenant_id`

请求体：

```json
{
  "tenant_name": "演示租户",
  "api_key": "demo-key",
  "is_active": true,
  "default_llm_model": "",
  "timeout_seconds": 30,
  "max_retries": 2
}
```

请求示例：

```bash
curl -X POST "http://127.0.0.1:8000/tenants" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name": "演示租户",
    "api_key": "demo-key"
  }'
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tenant_id": "tenant",
    "tenant_name": "演示租户",
    "api_key": "demo-key",
    "is_active": true,
    "default_llm_model": "",
    "timeout_seconds": 30,
    "max_retries": 2
  }
}
```

### 4. 更新租户

`PUT /tenants/{tenant_id}`

用途：
- 更新指定租户
- 这是兼容保留的老接口，推荐仅在显式指定租户时使用

鉴权：
- 需要 `X-API-Key`
- 路径中的 `tenant_id` 必须与 API key 对应租户一致

请求体：

```json
{
  "tenant_name": "演示租户",
  "api_key": "demo-key",
  "is_active": true,
  "default_llm_model": "gpt-5.4",
  "timeout_seconds": 30,
  "max_retries": 2
}
```

## 飞书配置接口

### 5. 获取当前租户飞书配置

`GET /tenant/feishu`

用途：
- 获取当前 API key 所属租户的飞书配置

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/tenant/feishu"
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tenant_id": "default",
    "tenant_name": "默认租户",
    "api_key": "your-api-key",
    "is_active": true,
    "default_llm_model": "",
    "timeout_seconds": 30,
    "max_retries": 2,
    "app_id": "cli_xxx",
    "app_secret": "secret",
    "tenant_access_token": "",
    "config": {}
  }
}
```

### 6. 更新当前租户飞书配置

`PUT /tenant/feishu`

用途：
- 为当前租户写入或更新飞书配置

请求体：

```json
{
  "tenant_name": "默认租户",
  "app_id": "cli_xxx",
  "app_secret": "secret",
  "tenant_access_token": "",
  "base_url": "https://example.com/base",
  "industry_report_url": "https://example.com/report",
  "marketing_plan_url": "https://example.com/plan",
  "keyword_matrix_url": "https://example.com/keyword",
  "default_llm_model": "gpt-5.4",
  "timeout_seconds": 30,
  "max_retries": 2
}
```

说明：
- `base_url`、`industry_report_url`、`marketing_plan_url`、`keyword_matrix_url` 为必填
- 服务端会调用飞书配置构建逻辑并写入 PostgreSQL

### 7. 兼容保留的显式租户飞书接口

- `GET /tenants/{tenant_id}/feishu`
- `PUT /tenants/{tenant_id}/feishu`

用途：
- 与 `/tenant/feishu` 行为一致
- 适用于调用方仍保留显式 `tenant_id` 的场景

## 调度接口

### 8. 获取当前租户调度列表

`GET /tenant/schedules`

用途：
- 获取当前租户所有 flow 的调度配置

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/tenant/schedules"
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "schedules": []
  }
}
```

### 9. 获取当前租户单个调度详情

`GET /tenant/schedules/{flow_id}`

用途：
- 获取当前租户某个 flow 的调度配置

### 10. 写入当前租户调度配置

`PUT /tenant/schedules/{flow_id}`

用途：
- 为当前租户某个 flow 创建或更新 cron 调度

请求体：

```json
{
  "cron": "*/15 * * * *",
  "is_active": true,
  "batch_id_prefix": "daily-report",
  "request_payload": {
    "source_url": ""
  }
}
```

字段说明：
- `cron`: 五段式 cron 表达式
- `is_active`: 是否启用
- `batch_id_prefix`: 生成调度 `batch_id` 时使用的前缀
- `request_payload.source_url`: 调度触发时传给工作流的请求参数

### 11. 删除当前租户调度

`DELETE /tenant/schedules/{flow_id}`

用途：
- 删除当前租户某个 flow 的调度配置

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tenant_id": "default",
    "flow_id": "daily-report",
    "deleted": true
  }
}
```

### 12. 手动触发当前租户调度

`POST /tenant/schedules/{flow_id}/trigger`

用途：
- 复用已保存的调度配置手动执行一次 flow

说明：
- 这个接口当前会同步执行，调用时可能耗时较长

### 13. 兼容保留的显式租户调度接口

- `GET /tenants/{tenant_id}/schedules`
- `GET /tenants/{tenant_id}/schedules/{flow_id}`
- `PUT /tenants/{tenant_id}/schedules/{flow_id}`
- `DELETE /tenants/{tenant_id}/schedules/{flow_id}`
- `POST /tenants/{tenant_id}/schedules/{flow_id}/trigger`

## Flow 查询与执行接口

### 14. 获取 flow 列表

`GET /flows`

用途：
- 获取当前服务支持的 flow 列表

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/flows"
```

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "flows": [
      { "id": "content-collect" },
      { "id": "content-create-original" },
      { "id": "content-create-rewrite" },
      { "id": "daily-report" }
    ]
  }
}
```

### 15. 创建一次 flow 运行

`POST /flows/{flow_id}/runs`

用途：
- 创建一次新的 run 资源
- 接口会立即返回，不等待流程执行完成
- 返回 `batch_id` 后，应使用查询接口轮询状态

请求体：

```json
{
  "tenant_id": "default",
  "batch_id": null,
  "source_url": ""
}
```

字段说明：
- `tenant_id`: 可选。默认推荐不传，由 API key 自动识别当前租户
- `batch_id`: 可选。不传时服务端按当前时间生成，格式为 `YYYYMMDDHHMMSS`
- `source_url`: 对需要源内容的 flow 生效，例如内容采集、内容改写

推荐调用示例：

```bash
curl -X POST "http://127.0.0.1:8000/flows/content-collect/runs" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "source_url": "https://example.com/post"
  }'
```

成功返回示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "running",
    "tenant_id": "default",
    "flow_id": "content-collect",
    "batch_id": "20260423123015",
    "run_path": "/flows/content-collect/runs/20260423123015"
  }
}
```

### 16. 查询当前租户某次运行状态

`GET /flows/{flow_id}/runs/{batch_id}`

用途：
- 查询当前 API key 所属租户在指定 `batch_id` 下的运行状态

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/flows/content-collect/runs/20260423123015"
```

可能返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "flow_id": "content-collect",
    "tenant_id": "default",
    "batch_id": "20260423123015",
    "source_url": "https://example.com/post",
    "status": "running",
    "current_node": "step-01",
    "completed_nodes": [],
    "node_statuses": {},
    "started_at": "2026-04-23 12:30:15",
    "updated_at": "2026-04-23 12:30:15",
    "outputs": {},
    "artifacts": {},
    "messages": [],
    "errors": []
  }
}
```

状态说明：
- `pending`: 已创建，尚未开始
- `running`: 执行中
- `completed`: 成功完成
- `blocked`: 被业务阻断
- `failed`: 执行失败

### 17. 恢复某次失败运行

`POST /flows/{flow_id}/runs/{batch_id}/resume`

用途：
- 对当前租户指定 `batch_id` 的 `failed` 或 `blocked` 运行发起恢复

请求示例：

```bash
curl -X POST "http://127.0.0.1:8000/flows/content-collect/runs/20260423123015/resume" \
  -H "X-API-Key: your-api-key"
```

说明：
- 当前恢复接口仍为同步返回，会在恢复流程跑完后返回结果

### 18. 兼容保留的显式租户运行接口

- `GET /flows/{flow_id}/runs/{tenant_id}/{batch_id}`
- `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume`

用途：
- 与推荐路径功能一致
- 适用于保留显式 `tenant_id` 路径的老调用方

## 参数校验错误示例

当请求体缺少必填字段时，会返回：

```json
{
  "code": 422,
  "message": "validation error",
  "data": [
    {
      "type": "missing",
      "loc": ["body", "tenant_name"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

## 常见错误示例

### 缺少 API key

```json
{
  "code": 401,
  "message": "缺少 X-API-Key",
  "data": ""
}
```

### API key 无效

```json
{
  "code": 401,
  "message": "X-API-Key 无效",
  "data": ""
}
```

### tenant 与 API key 不匹配

```json
{
  "code": 403,
  "message": "X-API-Key 与 tenant_id 不匹配",
  "data": ""
}
```

### PostgreSQL 未配置

```json
{
  "code": 400,
  "message": "缺少 DATABASE_URL，当前未启用 PostgreSQL 配置",
  "data": ""
}
```

### 运行不存在

```json
{
  "code": 404,
  "message": "run not found",
  "data": ""
}
```
