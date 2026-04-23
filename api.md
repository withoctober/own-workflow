# API 文档

本文档面向接口调用方，说明当前服务的鉴权方式、统一返回结构，以及所有 RESTful API 的调用方法。

## 基础信息

- Base URL: `http://<host>:<port>`
- Content-Type: `application/json`
- 鉴权头: `X-API-Key`

示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/flows"
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
- `403`: 请求体中的显式 `tenant_id` 与 API key 不匹配
- `404`: 资源不存在
- `422`: 请求体验证失败
- `500`: 服务内部错误
- `503`: 下游依赖暂不可用

## 鉴权规则

### 免鉴权接口

- `GET /api/health`
- `GET /api/tenants`
- `POST /api/tenants`

### 受保护接口

其余接口都需要通过请求头传 `X-API-Key`。

当前服务会根据 `X-API-Key` 反查租户，调用接口时不需要在路径中携带 `tenant_id`。

个别请求体仍允许可选传 `tenant_id`，但不推荐。传入时该值必须和 `X-API-Key` 绑定的租户一致，否则会返回：

```json
{
  "code": 403,
  "message": "X-API-Key 与 tenant_id 不匹配",
  "data": ""
}
```

## 推荐调用路径

建议优先使用以下不显式携带 `tenant_id` 的路径：

- `GET /api/tables`
- `GET /api/tables/{dataset_key}`
- `POST /api/tables/{dataset_key}`
- `PUT /api/tables/{dataset_key}/{record_id}`
- `DELETE /api/tables/{dataset_key}/{record_id}`
- `GET /api/flows`
- `POST /api/flows/{flow_id}/runs`
- `GET /api/flows/{flow_id}/runs/{batch_id}`
- `POST /api/flows/{flow_id}/runs/{batch_id}/resume`
- `GET /api/schedules`
- `GET /api/schedules/{flow_id}`
- `PUT /api/schedules/{flow_id}`
- `DELETE /api/schedules/{flow_id}`
- `POST /api/schedules/{flow_id}/trigger`

## 租户接口

### 1. 健康检查

`GET /api/health`

用途：
- 检查服务是否存活

请求示例：

```bash
curl "http://127.0.0.1:8000/api/health"
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

`GET /api/tenants`

用途：
- 获取当前所有租户

请求示例：

```bash
curl "http://127.0.0.1:8000/api/tenants"
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

`POST /api/tenants`

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
curl -X POST "http://127.0.0.1:8000/api/tenants" \
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

## 表格数据接口

### 4. 获取当前租户可操作表格列表

`GET /api/tables`

用途：
- 获取当前租户下所有内置表格类数据集

成功返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tables": [
      {
        "dataset_key": "products",
        "dataset_name": "产品库",
        "fields": ["产品名称", "价格", "产品定位", "目标人群", "竞品定位", "利润空间"]
      },
      {
        "dataset_key": "benchmark_accounts",
        "dataset_name": "对标账号库",
        "fields": ["主页链接", "账号名称", "配图链接", "头像链接", "粉丝数", "账号简介", "标签", "地区", "认证信息", "小红书号", "点赞收藏数", "互动率", "账号定位", "高频选题", "互动区问题类型", "转化动作"]
      }
    ]
  }
}
```

### 5. 获取当前租户某个表格的数据列表

`GET /api/tables/{dataset_key}`

用途：
- 按 `dataset_key` 读取某个表格类数据集的全部记录

### 6. 新增当前租户某个表格中的一条记录

`POST /api/tables/{dataset_key}`

请求体：

```json
{
  "payload": {
    "产品名称": "新品",
    "价格": "99"
  }
}
```

说明：
- `payload` 为行内容
- 可选传 `record_id`，不传则由系统生成

### 7. 编辑当前租户某个表格中的一条记录

`PUT /api/tables/{dataset_key}/{record_id}`

请求体：

```json
{
  "payload": {
    "产品名称": "更新后新品",
    "价格": "199"
  }
}
```

### 8. 删除当前租户某个表格中的一条记录

`DELETE /api/tables/{dataset_key}/{record_id}`

用途：
- 软删除对应记录

## 调度接口

### 9. 获取当前租户调度列表

`GET /api/schedules`

用途：
- 获取当前租户所有 flow 的调度配置

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/schedules"
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

### 10. 获取当前租户单个调度详情

`GET /api/schedules/{flow_id}`

用途：
- 获取当前租户某个 flow 的调度配置

### 11. 写入当前租户调度配置

`PUT /api/schedules/{flow_id}`

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

### 12. 删除当前租户调度

`DELETE /api/schedules/{flow_id}`

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

### 13. 手动触发当前租户调度

`POST /api/schedules/{flow_id}/trigger`

用途：
- 复用已保存的调度配置手动执行一次 flow

说明：
- 这个接口当前会同步执行，调用时可能耗时较长

## Flow 查询与执行接口

### 14. 获取 flow 列表

`GET /api/flows`

用途：
- 获取当前服务支持的 flow 列表

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/flows"
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

`POST /api/flows/{flow_id}/runs`

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
curl -X POST "http://127.0.0.1:8000/api/flows/content-collect/runs" \
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
    "run_path": "/api/flows/content-collect/runs/20260423123015"
  }
}
```

### 16. 查询当前租户某次运行状态

`GET /api/flows/{flow_id}/runs/{batch_id}`

用途：
- 查询当前 API key 所属租户在指定 `batch_id` 下的运行状态

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/flows/content-collect/runs/20260423123015"
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

### 17. 查询当前租户运行列表

`GET /api/runs`

用途：
- 查询当前 API key 所属租户的全部运行记录列表
- 列表数据来自 PostgreSQL 中的 `workflow_runs` 元数据表
- 详细运行状态仍可通过单次查询接口读取对应 `state.json`

查询参数：
- `flow_id`: 可选，按 flow 过滤
- `status`: 可选，按运行状态过滤
- `limit`: 可选，默认 `20`，最大 `200`
- `offset`: 可选，默认 `0`

请求示例：

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/runs?flow_id=content-collect&status=completed&limit=20&offset=0"
```

成功返回示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tenant_id": "default",
    "total": 1,
    "limit": 20,
    "offset": 0,
    "runs": [
      {
        "tenant_id": "default",
        "flow_id": "content-collect",
        "batch_id": "20260423123015",
        "source_url": "https://example.com/post",
        "status": "completed",
        "current_node": "",
        "resume_count": 1,
        "completed_node_count": 8,
        "error_count": 0,
        "last_message": "流程执行完成",
        "last_error": "",
        "started_at": "2026-04-23T12:30:15+08:00",
        "updated_at": "2026-04-23T12:31:42+08:00",
        "finished_at": "2026-04-23T12:31:42+08:00",
        "run_path": "/api/flows/content-collect/runs/20260423123015"
      }
    ]
  }
}
```

### 18. 恢复某次失败运行

`POST /api/flows/{flow_id}/runs/{batch_id}/resume`

用途：
- 对当前租户指定 `batch_id` 的 `failed` 或 `blocked` 运行发起恢复

请求示例：

```bash
curl -X POST "http://127.0.0.1:8000/api/flows/content-collect/runs/20260423123015/resume" \
  -H "X-API-Key: your-api-key"
```

说明：
- 当前恢复接口仍为同步返回，会在恢复流程跑完后返回结果

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
