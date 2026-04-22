# own-workflow

基于 LangGraph 的小红书工作流服务，当前项目只保留一套运行时实现，不再依赖旧的 `xhs_graph/`、`flows/`、`runtime/` 平铺目录或 `dry_run` 分支。

## 目录结构

```text
own-workflow/
├── app/                # 应用壳层：HTTP 路由、租户初始化、store/integration/core 等支撑
├── workflow/           # 工作流实现：flow / runtime / state / core / store / integrations
├── tests/              # 运行时与图装配 smoke tests
└── var/runs/           # 运行产物目录
```

## 当前流程

- `content-collect`
- `daily-report`
- `content-create-original`
- `content-create-rewrite`

每条流程都聚合在各自的 `workflow/flow/<flow_name>/` 目录下，运行时通过 LangGraph `StateGraph` 串联执行；如果依赖缺失或外部接口不可用，流程会返回受控 `blocked` 状态，而不是走占位输出。

## 安装

```bash
uv sync
```

## 启动服务

```bash
uv run uvicorn app.main:app --reload
```

当前服务端接口已经固定为 Feishu store 模式，不再支持传入 `store_backend`、`data_dir` 或本地文件型 store 配置。

`app/` 当前只保留应用入口层：

- `app/main.py`: 创建 FastAPI 应用并挂载运行时对象
- `app/routes.py`: HTTP 路由
- `app/schemas.py`: 请求模型
- `app/dependencies.py`: 依赖注入与运行状态读取
- `app/settings.py`: 项目级路径配置

`workflow/` 当前按工作流实现结构拆分：

- `workflow/flow/`: 具体流程定义
- `workflow/runtime/`: GraphRuntime、状态持久化、执行上下文
- `workflow/state.py`: LangGraph state 定义
- `workflow/core/`: 环境变量、文本工具、模型调用、prompt 渲染等基础能力
- `workflow/store/`: store 协议、飞书后端与工厂装配
- `workflow/integrations/`: 第三方接口访问

默认接口：

- `GET /health`
- `GET /tenants`
- `POST /tenants`
- `PUT /tenants/{tenant_id}`
- `GET /tenants/{tenant_id}/feishu`
- `PUT /tenants/{tenant_id}/feishu`
- `GET /tenants/{tenant_id}/schedules`
- `GET /tenants/{tenant_id}/schedules/{flow_id}`
- `PUT /tenants/{tenant_id}/schedules/{flow_id}`
- `DELETE /tenants/{tenant_id}/schedules/{flow_id}`
- `POST /tenants/{tenant_id}/schedules/{flow_id}/trigger`
- `GET /flows`
- `POST /flows/{flow_id}/runs`
- `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume`
- `GET /flows/{flow_id}/runs/{tenant_id}/{batch_id}`

## 运行方式

启动一次流程：

```bash
curl -X POST "http://127.0.0.1:8000/flows/content-collect/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default"
  }'
```

如果要运行 `content-create-rewrite`，请求体还需要补 `source_url`：

```bash
curl -X POST "http://127.0.0.1:8000/flows/content-create-rewrite/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "source_url": "https://www.xiaohongshu.com/explore/xxxx"
  }'
```

查询运行结果：

```bash
curl "http://127.0.0.1:8000/flows/content-collect/runs/default/20260421123000"
```

对失败或阻塞的 run 发起恢复：

```bash
curl -X POST "http://127.0.0.1:8000/flows/content-collect/runs/default/20260421123000/resume"
```

`resume` 会沿用原来的 `batch_id` 和运行目录，只重试失败节点及其后续节点；已经完成的节点会被跳过，不会重复执行。

运行状态会落到 `var/runs/{tenant_id}/{flow_id}/{batch_id}/state.json`，同时保存 LangGraph checkpoint 和各节点产物。

## Store 与多租户

项目当前固定使用 `feishu` 数据后端，并且**只支持 PostgreSQL 租户配置**。

这意味着：

- 请求体里只需要传业务相关字段，不再接受 store 选择参数
- 本地 `data/tables`、`data/docs` 目录不再是运行前提
- 是否能跑通流程，取决于租户飞书配置是否存在，以及对应资源映射是否完整

### PostgreSQL 多租户配置

如果你要用数据库管理租户配置，需要先准备：

- `DATABASE_URL`
- 安装依赖：`uv sync`

当前数据库侧最小使用两张表：

- `tenants`
- `tenant_feishu_configs`

服务启动后不需要手工先建表；只要调用租户相关接口，服务会自动执行最小建表。

数据库里保存的是：

- 租户基础信息
- 飞书 `app_id`
- 飞书 `app_secret`
- 可选的 `tenant_access_token`
- `tables/docs` 等运行配置 `jsonb`

按你当前要求，`app_id` 和 `app_secret` 是**明文存库**，不做加密。

### PostgreSQL 接口示例

创建租户（只传租户名称，由服务端自动生成 `tenant_id`）：

```bash
curl -X POST "http://127.0.0.1:8000/tenants" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name": "默认租户",
    "is_active": true,
    "default_llm_model": "",
    "timeout_seconds": 30,
    "max_retries": 2
  }'
```

兼容方式：按指定 `tenant_id` 创建或更新租户基础信息：

```bash
curl -X PUT "http://127.0.0.1:8000/tenants/default" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name": "默认租户",
    "is_active": true,
    "default_llm_model": "",
    "timeout_seconds": 30,
    "max_retries": 2
  }'
```

查询所有租户：

```bash
curl "http://127.0.0.1:8000/tenants"
```

写入租户飞书配置：

```bash
curl -X PUT "http://127.0.0.1:8000/tenants/default/feishu" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name": "默认租户",
    "app_id": "cli_xxx",
    "app_secret": "xxx",
    "tenant_access_token": "",
    "base_url": "https://my.feishu.cn/base/xxxx?table=tblxxxx",
    "industry_report_url": "https://my.feishu.cn/docx/xxxx",
    "marketing_plan_url": "https://my.feishu.cn/docx/yyyy",
    "keyword_matrix_url": "https://my.feishu.cn/docx/zzzz",
    "default_llm_model": "",
    "timeout_seconds": 30,
    "max_retries": 2
  }'
```

查询指定租户飞书配置：

```bash
curl "http://127.0.0.1:8000/tenants/default/feishu"
```

这组接口会做两件事：

- 调飞书接口校验 `app_id/app_secret` 和目标文档/多维表格
- 把解析后的 `tables/docs` 写入 PostgreSQL

### 租户工作流定时任务

当前服务支持为租户的工作流配置 cron schedule，并保证每个租户的每个工作流只能有 1 条 schedule。

数据库会自动补齐第三张表：

- `tenant_flow_schedules`

写入或更新 schedule：

```bash
curl -X PUT "http://127.0.0.1:8000/tenants/default/schedules/daily-report" \
  -H "Content-Type: application/json" \
  -d '{
    "cron": "0 9 * * *",
    "is_active": true,
    "batch_id_prefix": "daily-report",
    "request_payload": {
      "source_url": ""
    }
  }'
```

查询租户下所有 schedule：

```bash
curl "http://127.0.0.1:8000/tenants/default/schedules"
```

查询指定工作流的 schedule 详情：

```bash
curl "http://127.0.0.1:8000/tenants/default/schedules/daily-report"
```

删除指定工作流的 schedule：

```bash
curl -X DELETE "http://127.0.0.1:8000/tenants/default/schedules/daily-report"
```

手动按 schedule 配置触发一次工作流：

```bash
curl -X POST "http://127.0.0.1:8000/tenants/default/schedules/daily-report/trigger"
```

如果服务保持运行，应用启动时会自动恢复激活中的 schedule，并在 `next_run_at` 到期时后台触发对应工作流执行，同时回写最近执行状态、错误信息和下一次执行时间。

## 环境变量

按实际流程准备以下变量：

- `DATABASE_URL`，启用 PostgreSQL 多租户配置时必填
- `OPENAI_API_KEY` 或兼容的模型接入配置，用于 LangChain / LangGraph 节点里的大模型调用
- `TIKHUB_API_KEY`，用于热点和二创抓取
- `ARK_API_KEY`，用于图片生成

项目会优先读取进程环境变量；若不存在，再回退到项目根目录 `.env`。

如果只想确认服务能启动，不一定要立刻配齐所有变量；但只要触发真实流程节点，缺少对应变量就会在运行阶段失败或进入 `blocked` 状态。

## 开发说明

- Flow 相关代码统一放在 `workflow/flow/<flow_name>/`，单条流程的图定义、节点和生成逻辑在同一目录中维护
- Prompt 模板跟随 flow 放在各自 `prompts/` 子目录
- workflow runtime 收口到 `workflow/runtime/`
- 通用模型调用、消息构建和 prompt 渲染收口到 `workflow/core/`
- 第三方接口能力收口到 `workflow/integrations/`
- store 适配层收口到 `workflow/store/`
- 不再保留 `dry_run` 分支，验证请使用真实输入或受控阻断路径
