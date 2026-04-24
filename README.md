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

## Docker

构建镜像：

```bash
docker build -t own-workflow:local .
```

运行镜像：

```bash
docker run --rm -p 8000:8000 --env-file .env own-workflow:local
```

使用 Docker Compose 直接启动：

```bash
docker compose up
```

Compose 只启动当前应用服务，并直接拉取已发布镜像 `uswccr.ccs.tencentyun.com/inpolar/own-workflow:main`。它会复用仓库根目录 `.env` 中已有的 `DATABASE_URL` 等环境变量，不会额外创建 PostgreSQL 容器。

如果要修改宿主机映射端口，可以在 `.env` 中增加：

```bash
APP_PORT=9000
```

这样 Compose 会把宿主机 `9000` 端口映射到容器内固定的 `8000` 端口。

镜像默认启动命令等价于：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

当前服务端接口已经固定为 Database store 模式，不再支持传入 `store_backend`、`data_dir` 或本地文件型 store 配置。

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
- `workflow/store/`: store 协议、数据库后端与工厂装配
- `workflow/integrations/`: 第三方接口访问

默认接口：

- `GET /api/health`
- `GET /api/tenants`
- `POST /api/tenants`
- `GET /api/flows`
- `POST /api/flows/{flow_id}/runs`
- `POST /api/flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume`
- `GET /api/flows/{flow_id}/runs/{tenant_id}/{batch_id}`

## 运行方式

启动一次流程：

```bash
curl -X POST "http://127.0.0.1:8000/api/flows/content-collect/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default"
  }'
```

如果要运行 `content-create-rewrite`，请求体还需要补 `source_url`：

```bash
curl -X POST "http://127.0.0.1:8000/api/flows/content-create-rewrite/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "source_url": "https://www.xiaohongshu.com/explore/xxxx"
  }'
```

查询运行结果：

```bash
curl "http://127.0.0.1:8000/api/flows/content-collect/runs/default/20260421123000"
```

对失败或阻塞的 run 发起恢复：

```bash
curl -X POST "http://127.0.0.1:8000/api/flows/content-collect/runs/default/20260421123000/resume"
```

`resume` 会沿用原来的 `batch_id` 和运行目录，只重试失败节点及其后续节点；已经完成的节点会被跳过，不会重复执行。

运行状态会落到 `var/runs/{tenant_id}/{flow_id}/{batch_id}/state.json`，同时保存 LangGraph checkpoint 和各节点产物。

## Store 与多租户

项目当前固定使用数据库数据后端，并且**只支持 PostgreSQL 租户配置**。

这意味着：

- 请求体里只需要传业务相关字段，不再接受 store 选择参数
- 本地 `data/tables`、`data/docs` 目录不再是运行前提
- 是否能跑通流程，取决于租户基础配置是否存在，以及数据库连接是否可用

### PostgreSQL 多租户配置

如果你要用数据库管理租户配置，需要先准备：

- `DATABASE_URL`
- 安装依赖：`uv sync`

当前数据库侧最小使用两张表：

- `tenants`
- `store_entries`

服务启动后不需要手工先建表；只要调用租户相关接口，服务会自动执行最小建表。

数据库里保存的是：

- 租户基础信息
- 租户 API 模式与自定义 API 配置
- 运行时默认超时与重试配置
- 各数据集的结构化数据与文档内容

### PostgreSQL 接口示例

创建租户（只传租户名称，由服务端自动生成 `tenant_id`）：

```bash
curl -X POST "http://127.0.0.1:8000/api/tenants" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name": "默认租户",
    "api_key": "default-key",
    "is_active": true,
    "default_llm_model": "",
    "api_mode": "custom",
    "api_ref": {
      "OPENAI_API_KEY": "tenant-openai-key",
      "OPENAI_BASE_URL": "https://api.openai.com/v1",
      "OPENAI_MODEL": "gpt-4.1-mini",
      "TIKHUB_API_KEY": "tenant-tikhub-key",
      "ARK_API_KEY": "tenant-ark-key"
    },
    "timeout_seconds": 600,
    "max_retries": 2
  }'
```

查询所有租户：

```bash
curl "http://127.0.0.1:8000/api/tenants"
```

`api_mode` 说明：

- `system`：运行时读取系统环境变量，忽略租户 `api_ref`
- `custom`：运行时优先读取租户 `api_ref`

`api_ref` 约定使用环境变量风格键名，例如：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `TIKHUB_API_KEY`
- `ARK_API_KEY`

### 租户工作流定时任务

当前服务支持为租户的工作流配置 cron schedule，并保证每个租户的每个工作流只能有 1 条 schedule。

数据库会自动补齐第三张表：

- `tenant_flow_schedules`

写入或更新 schedule：

```bash
curl -X PUT "http://127.0.0.1:8000/api/schedules/daily-report" \
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
curl "http://127.0.0.1:8000/api/schedules"
```

查询指定工作流的 schedule 详情：

```bash
curl "http://127.0.0.1:8000/api/schedules/daily-report"
```

删除指定工作流的 schedule：

```bash
curl -X DELETE "http://127.0.0.1:8000/api/schedules/daily-report"
```

手动按 schedule 配置触发一次工作流：

```bash
curl -X POST "http://127.0.0.1:8000/api/schedules/daily-report/trigger"
```

如果服务保持运行，应用启动时会自动恢复激活中的 schedule，并在 `next_run_at` 到期时后台触发对应工作流执行，同时回写最近执行状态、错误信息和下一次执行时间。

## 环境变量

按实际流程准备以下变量：

- `DATABASE_URL`，启用 PostgreSQL 多租户配置时必填
- `OPENAI_API_KEY` 或兼容的模型接入配置，用于 LangChain / LangGraph 节点里的大模型调用
- `TIKHUB_API_KEY`，用于热点和二创抓取
- `ARK_API_KEY`，用于图片生成
- `S3_ENDPOINT`，S3 兼容对象存储上传地址
- `S3_REGION`，S3 SigV4 所需 region
- `S3_BUCKET`，图片上传目标 bucket
- `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`，S3 上传凭证
- `S3_SESSION_TOKEN`，可选，使用临时凭证时提供
- `S3_KEY_PREFIX`，可选，统一对象前缀
- `S3_PUBLIC_BASE_URL`，可选，对外访问域名或 CDN 前缀；未提供时默认返回 bucket 对象 URL

项目会优先读取进程环境变量；若不存在，再回退到项目根目录 `.env`。

当租户 `api_mode=custom` 时，LLM、TikHub、Ark 生图配置可由租户 `api_ref` 覆盖；S3 上传始终读取系统环境变量或项目根目录 `.env`，不走租户配置。

当前 `content_create` 流程会在 AI 出图成功后自动将封面图和配图转存到 S3，再把 S3 URL 写入生成作品库；抓取图和参考图流程暂不受影响。

如果只想确认服务能启动，不一定要立刻配齐所有变量；但只要触发真实流程节点，缺少对应变量就会在运行阶段失败或进入 `blocked` 状态。

## 开发说明

- Flow 相关代码统一放在 `workflow/flow/<flow_name>/`，单条流程的图定义、节点和生成逻辑在同一目录中维护
- Prompt 模板跟随 flow 放在各自 `prompts/` 子目录
- workflow runtime 收口到 `workflow/runtime/`
- 通用模型调用、消息构建和 prompt 渲染收口到 `workflow/core/`
- 第三方接口能力收口到 `workflow/integrations/`
- store 适配层收口到 `workflow/store/`
- 不再保留 `dry_run` 分支，验证请使用真实输入或受控阻断路径
