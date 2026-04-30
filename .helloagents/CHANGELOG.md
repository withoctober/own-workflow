# CHANGELOG

## [0.8.2] - 2026-04-30

### 新增
- **[integrations]**: `ark`/volc 图片 provider 支持参考图编辑；传入参考图时直接把 S3 URL 或 Base64 写入火山 `image` 字段，单图用字符串、多图用数组，并移除图片 provider 默认配置回退，统一要求显式配置 `IMAGE_PROVIDER`、`IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL` — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: workflow/integrations/image_generation.py, tests/test_content_create_images.py

## [0.8.1] - 2026-04-28

### 修复
- **[flows]**: 原创/二创配图提示词归一化后新增 `cover_prompt` 非空校验，避免空提示词继续进入图片生成接口 — by withoctober
  - 方案: [202604282222_fix-uni-image-prompt-field](archive/2026-04/202604282222_fix-uni-image-prompt-field/)
  - 决策: fix-uni-image-prompt-field#D001(保持 Uni 小写 prompt，并在本地拦截空值)
- **[integrations]**: `generate_images()` 会在调用 provider 前逐项拦截空 prompt，避免 Uni 远端返回 `field Prompt is required` 这类参数错误，同时防止过滤空值造成图片槽位错位 — by withoctober
  - 方案: [202604282222_fix-uni-image-prompt-field](archive/2026-04/202604282222_fix-uni-image-prompt-field/)
  - 决策: fix-uni-image-prompt-field#D001(保持 Uni 小写 prompt，并在本地拦截空值)

## [0.8.0] - 2026-04-28

### 新增
- **[app]**: 新增 `POST /api/artifacts/{artifact_id}/preview-image-edit` 作品图片编辑预览接口，返回生成图 URL 但不更新 artifact；现有 `regenerate-image` 保持立即保存语义并复用同一图片编辑生成逻辑 — by withoctober
  - 方案: [202604282104_artifact-image-edit-preview](archive/2026-04/202604282104_artifact-image-edit-preview/)
  - 决策: artifact-image-edit-preview#D001(新增独立预览接口)
- **[integrations]**: 新增 `uni` 图片 provider，复用 `IMAGE_PROVIDER=uni` 与 `IMAGE_API_*` 配置，按 UniAPI JSON `/images/generations` 和 multipart `image[]` `/images/edits` 协议支持图片生成与编辑，并继续复用 S3 上传链路 — by withoctober
  - 方案: [202604282039_uni-image-provider](archive/2026-04/202604282039_uni-image-provider/)
  - 决策: uni-image-provider#D001(UniProvider 复用 IMAGE_API_* 配置)

## [0.7.5] - 2026-04-28

### 新增
- **[integrations]**: 图片生成配置统一收敛为 `IMAGE_PROVIDER`、`IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL`，同时支持租户 `api_ref` 与系统环境变量，不再读取旧的 `OPENAI_IMAGE_*`、`OPENAI_*` 或 `ARK_*` 图片配置 — by withoctober
  - 方案: [202604281754_image-api-config](archive/2026-04/202604281754_image-api-config/)
  - 决策: image-api-config#D001(图片配置统一为 IMAGE_API_* 变量)
- **[app]**: 租户 `api_mode=custom` 校验同步要求新的图片配置键，并更新 README、api 文档与环境变量示例 — by withoctober
  - 方案: [202604281754_image-api-config](archive/2026-04/202604281754_image-api-config/)
  - 决策: image-api-config#D001(图片配置统一为 IMAGE_API_* 变量)
- **[flows]**: `content_create` 与作品库图片重生成不再硬编码 OpenAI provider 和 `gpt-image-2`，统一由图片集成层按当前租户或环境配置解析 — by withoctober
  - 方案: [202604281754_image-api-config](archive/2026-04/202604281754_image-api-config/)
  - 决策: image-api-config#D001(图片配置统一为 IMAGE_API_* 变量)
- **[integrations]**: 新增 `blt` 图片 provider，按用户提供的 BLT API 协议使用 JSON `/images/generations` 生图、multipart `/images/edits` 改图，并复用现有 `IMAGE_PROVIDER` 与 `IMAGE_API_*` 配置 — by withoctober
  - 方案: [202604281828_blt-image-provider](archive/2026-04/202604281828_blt-image-provider/)
  - 决策: blt-image-provider#D001(BLT provider 复用 IMAGE_API_* 配置)

### 快速修改
- **[delivery]**: 将 README 本地启动命令的监听地址改为 `0.0.0.0`，与容器默认启动命令保持一致 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: README.md:33
- **[integrations]**: BLT 图片编辑改为仅使用当前编辑图片 URL，并通过 multipart 表单字段 `image=<url>` 调用 `/images/edits`，避免下载作品库中的额外参考图 — by withoctober
  - 方案: [202604281848_blt-edit-url-reference](archive/2026-04/202604281848_blt-edit-url-reference/)
  - 决策: blt-edit-url-reference#D001(BLT 编辑图使用 URL 直传)

### 回滚
- **[integrations]**: 移除 `blt` 图片 provider，运行时和文档恢复为仅支持 `ark` 与 `openai`，同时删除 BLT 相关测试和作品库编辑特判 — by withoctober
  - 方案: [202604281903_remove-blt-image-provider](archive/2026-04/202604281903_remove-blt-image-provider/)
  - 原因: 用户要求回退并移除 BLT provider

## [0.7.4] - 2026-04-25

### 新增
- **[runtime]**: 为工作流运行历史新增 `trigger_mode` 元数据，统一区分 `manual` 与 `cron` 触发来源；该字段会同时写入 `state.json`、`workflow_runs`，并在 `resume` 时沿用原始触发方式 — by withoctober
  - 方案: [202604251010_execution-history-trigger-mode](plan/202604251010_execution-history-trigger-mode/)
  - 决策: execution-history-trigger-mode#D001(触发方式作为 run 元数据持久化字段统一收敛)
- **[app]**: `/api/runs` 与 run 详情接口开始返回 `trigger_mode`，调用方可直接在执行历史中展示“手动触发 / cron 触发”，并补充对应路由、调度器与持久化测试覆盖 — by withoctober
  - 方案: [202604251010_execution-history-trigger-mode](plan/202604251010_execution-history-trigger-mode/)
  - 决策: execution-history-trigger-mode#D001(触发方式作为 run 元数据持久化字段统一收敛)

## [0.7.3] - 2026-04-25

### 快速修改
- **[app]**: 定时任务保存时会过滤 `request_payload` 中的默认空值，避免 `content-create-original`、`daily-report` 这类无参 flow 落库冗余 `{\"source_url\": \"\"}`，并补充空参数与非空参数的路由测试覆盖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/routes.py, tests/test_app_routes.py

## [0.7.2] - 2026-04-25

### 快速修改
- **[integrations]**: 将 Ark 生图调用从 `content_create` 工具函数中抽离到独立 `workflow.integrations.image_generation` 单文件模块，统一收敛 provider 选择、请求分发与 S3 上传入口，并补充默认 Ark、租户自定义 provider 和不支持 provider 的测试覆盖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: workflow/integrations/image_generation.py, workflow/integrations/__init__.py, workflow/flow/content_create/nodes.py, workflow/flow/content_create/utils.py, tests/test_content_create_images.py

## [0.7.1] - 2026-04-24

### 新增
- **[app]**: `GET /api/flows` 进一步为每个工作流返回中文 `name` 和 `description`，前端现在可直接展示工作流名称、用途说明和执行参数 schema — by withoctober
  - 方案: [202604242207_flow-list-name-description](archive/2026-04/202604242207_flow-list-name-description/)
  - 决策: flow-list-name-description#D001(将展示文案与执行 schema 一并放入 flow 注册表)
- **[flows]**: 工作流注册表开始集中维护每个 flow 的中文展示元数据，与 `run_request_schema` 一起作为 `/api/flows` 的统一返回来源 — by withoctober
  - 方案: [202604242207_flow-list-name-description](archive/2026-04/202604242207_flow-list-name-description/)
  - 决策: flow-list-name-description#D001(将展示文案与执行 schema 一并放入 flow 注册表)

## [0.7.0] - 2026-04-24

### 新增
- **[app]**: `GET /api/flows` 现会为每个工作流返回完整 `run_request_schema`，包含字段类型、默认值、描述以及必填/选填标记，便于前端直接生成执行表单 — by withoctober
  - 方案: [202604242134_flow-list-required-params](archive/2026-04/202604242134_flow-list-required-params/)
  - 决策: flow-list-required-params#D001(返回完整运行参数 schema)
- **[flows]**: 工作流注册表新增集中式运行参数 schema 元数据，并按 flow 差异化声明 `tenant_id`、`batch_id` 与 `source_url` 的可用性和必填状态 — by withoctober
  - 方案: [202604242134_flow-list-required-params](archive/2026-04/202604242134_flow-list-required-params/)
  - 决策: flow-list-required-params#D001(返回完整运行参数 schema)

## [0.6.1] - 2026-04-24

### 修复
- **[app]**: 更新 `api.md`，补充 `GET /api/artifacts` 与 `GET /api/artifacts/{artifact_id}` 接口说明、返回示例以及真实运行验证记录；同时使用 `tenant-2` 成功跑通一次 `content-create-original`，确认批次 `20260424161200` 已正常写入 `artifacts` 表 — by withoctober
  - 方案: [202604241607_artifact-db-sync-and-flow-test](archive/2026-04/202604241607_artifact-db-sync-and-flow-test/)
  - 决策: artifact-db-sync-and-flow-test#D001(复用现有 uv 环境和 run_flow_once 脚本做真实流程验证)

## [0.6.0] - 2026-04-24

### 新增
- **[runtime]**: 新增独立 `artifacts` PostgreSQL 业务表及模型 CRUD，用于按租户、流程和批次持久化创作完成后的标题、正文、提示词与图片链接，不再只依赖运行目录 artifact 文件或通用 `store_entries` 数据集 — by withoctober
  - 方案: [202604241555_artifact-content-storage](plan/202604241555_artifact-content-storage/)
  - 决策: artifact-content-storage#D001(采用独立 artifact 业务表而不是扩展通用 store_entries)
- **[flows]**: `content_create` 流程在写入“生成作品库”时会同步写入 `artifacts` 业务表，并在节点输出与快照中记录 `artifact_id`，便于运行记录和业务成品双向追溯 — by withoctober
  - 方案: [202604241555_artifact-content-storage](plan/202604241555_artifact-content-storage/)
  - 决策: artifact-content-storage#D001(采用独立 artifact 业务表而不是扩展通用 store_entries)
- **[app]**: 新增 `GET /api/artifacts` 与 `GET /api/artifacts/{artifact_id}` 接口，支持当前租户按流程分页查询创作成品及读取单条详情，并补充路由与模型测试覆盖 — by withoctober
  - 方案: [202604241555_artifact-content-storage](plan/202604241555_artifact-content-storage/)
  - 决策: artifact-content-storage#D001(采用独立 artifact 业务表而不是扩展通用 store_entries)

## [0.5.1] - 2026-04-24

### 修复
- **[runtime]**: 修复 `resume` 成功后 `state.json` 里消息重复追加和失败节点残留的问题；恢复前会清理无关失败状态，完成落盘时不再把旧 `messages/errors` 二次累加 — by withoctober
  - 方案: [202604241523_resume-state-cleanup](plan/202604241523_resume-state-cleanup/)
  - 决策: resume-state-cleanup#D001(在 repository 内部收敛 resume 状态清理与最终态合并)

## [0.5.0] - 2026-04-24

### 新增
- **[integrations]**: 新增通用 `workflow.integrations.s3` 上传能力，统一从系统环境变量或项目根目录 `.env` 读取 S3 配置，并提供字节上传与远程 URL 转存入口，便于后续其他模块复用 — by withoctober
  - 方案: [202604241424_s3-image-upload](plan/202604241424_s3-image-upload/)
  - 决策: s3-image-upload#D001(使用标准库实现通用 S3 上传能力并在出图后转存)
- **[flows]**: `content_create` 流程的 AI 出图结果现会在落库前自动转存到 S3，作品库中的封面链接与配图链接统一保存为 S3 URL，并保留原始出图结果用于排查 — by withoctober
  - 方案: [202604241424_s3-image-upload](plan/202604241424_s3-image-upload/)
  - 决策: s3-image-upload#D001(使用标准库实现通用 S3 上传能力并在出图后转存)

## [0.4.2] - 2026-04-24

### 新增
- **[app]**: 为租户新增 `api_mode` 与 `api_ref` 配置，支持区分系统默认 API 配置与租户自定义配置，并在租户创建/查询接口中返回对应字段 — by withoctober
  - 方案: [202604241248_tenant-api-mode-api-ref](plan/202604241248_tenant-api-mode-api-ref/)
  - 决策: tenant-api-mode-api-ref#D001(使用统一 `api_mode + api_ref` 承载租户自定义第三方配置)
- **[runtime]**: 将租户级 API 配置注入工作流运行时，并让 LLM、TikHub、Ark 生图三条调用链支持优先读取租户 `api_ref`，未启用自定义时回退系统环境变量 — by withoctober
  - 方案: [202604241248_tenant-api-mode-api-ref](plan/202604241248_tenant-api-mode-api-ref/)
  - 决策: tenant-api-mode-api-ref#D001(使用统一 `api_mode + api_ref` 承载租户自定义第三方配置)

## [0.4.1] - 2026-04-23

### 快速修改
- **[app]**: 扩展作品库读取接口，使 `/api/tables` 返回表格类与文档类数据集，并让 `/api/tables/{dataset_key}` 将行业报告等文档包装为表格行返回 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/routes.py, workflow/store/database.py, tests/test_app_routes.py, api.md
- **[store]**: 补齐数据库 store 内置 dataset registry 字段，覆盖客户背景资料、产品库、对标账号库、每日热点与数据分析的业务列，保持统一 `store_entries` 物理表不变，并补充 API 目录与字段注册测试覆盖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: workflow/store/database.py, tests/test_store_database.py, tests/test_app_routes.py, api.md

## [0.4.0] - 2026-04-23

### 新增
- **[app]**: 依据 `api.md` 同步 HTTP API，统一公开路由到 `/api` 前缀，移除路径携带 `tenant_id` 的旧接口，补齐未注册路径的统一响应包装，并扩展鉴权、当前租户 run 查询/恢复和旧路径移除测试覆盖 — by withoctober
  - 方案: [202604232025_sync-api-md-interfaces](archive/2026-04/202604232025_sync-api-md-interfaces/)
  - 决策: sync-api-md-interfaces#D001(以 api.md 和用户补充约束作为接口规范来源，不保留路径带 tenant_id 的兼容接口)

## [0.3.5] - 2026-04-23

### 快速修改
- **[app]**: 为 FastAPI 应用入口增加全局 CORS 配置，允许任意域名、请求方法和请求头访问接口，并补充预检请求测试覆盖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/main.py, tests/test_app_routes.py

## [0.3.4] - 2026-04-23

### 快速修改
- **[store]**: 为飞书多维表格写入链路统一清理字符串字段前置空行，避免单元格内容写入前出现多余空白，并补充写入与更新路径的单元测试覆盖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: workflow/store/feishu.py, tests/test_store_feishu.py

## [0.3.3] - 2026-04-23

### 新增
- **[app]**: 为租户模型新增 `api_key` 字段，并为除 `/health` 与租户创建/列表外的业务接口接入统一 `X-API-Key` 租户级鉴权；服务端可直接通过 API key 反查租户，客户端默认无需再显式传 `tenant_id`，同时补齐路由与模型测试覆盖 — by withoctober
  - 方案: [202604231001_tenant-api-key-auth](plan/202604231001_tenant-api-key-auth/)
  - 决策: tenant-api-key-auth#D001(兼容保留老接口的 tenant_id 传参，但默认以 API key 反查租户为主；显式 tenant_id 若存在则必须匹配)
- **[app]**: 将 `POST /flows/{flow_id}/runs` 调整为真正的异步 RESTful 创建接口，立即返回 `batch_id/run_path`，后台执行流程，查询统一走 `GET /flows/{flow_id}/runs/{batch_id}` — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/routes.py, workflow/runtime/engine.py, tests/test_app_routes.py

## [0.3.2] - 2026-04-23

### 快速修改
- **[delivery]**: 为 `docker-compose.yml` 增加宿主机端口环境变量配置，支持通过 `APP_PORT` 覆盖默认 `8000` 端口 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: docker-compose.yml, README.md

## [0.3.1] - 2026-04-23

### 新增
- **[delivery]**: 新增根目录 `docker-compose.yml`，支持直接拉取已发布的 `main` 镜像并复用仓库 `.env` 启动当前应用服务 — by withoctober
  - 方案: [202604230912_compose-app-runtime](plan/202604230912_compose-app-runtime/)
  - 决策: compose-app-runtime#D001(Compose 仅封装应用服务并复用现有外部 PostgreSQL)

## [0.3.0] - 2026-04-23

### 新增
- **[delivery]**: 新增项目根目录 `Dockerfile` 与 GitHub Actions 镜像构建推送流程，支持在任意分支 push 时构建并推送当前 FastAPI 服务镜像到腾讯云镜像仓库 — by withoctober
  - 方案: [202604230847_dockerized-image-build](plan/202604230847_dockerized-image-build/)
  - 决策: dockerized-image-build#D001(容器镜像直接基于当前 uv 项目结构构建)

## [0.2.2] - 2026-04-23

### 新增
- **[runtime]**: 新增 `scripts/run_flow_once.py`，支持直接读取本地 `.env` 与 PostgreSQL 租户飞书配置触发单次工作流执行，并用于一次性延迟触发 `default` 租户的 `content-collect` — by withoctober
  - 方案: [202604230750_delayed-content-collect-default](plan/202604230750_delayed-content-collect-default/)
  - 决策: delayed-content-collect-default#D001(一次性任务采用系统 at 队列而非内置 cron schedule)

## [0.2.1] - 2026-04-23

### 新增
- **[runtime]**: 为工作流运行时新增显式 `resume` 恢复能力，可对失败或阻塞 run 沿用原 `batch_id` 重试，并跳过已完成节点 — by withoctober
  - 方案: [202604230714_run-resume-retry](plan/202604230714_run-resume-retry/)
  - 决策: run-resume-retry#D001(使用显式跳过已完成节点，而非依赖 LangGraph 自动 checkpoint 恢复)
- **[app]**: 新增 `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume` 接口，支持对指定失败 run 发起恢复 — by withoctober
  - 方案: [202604230714_run-resume-retry](plan/202604230714_run-resume-retry/)
  - 决策: run-resume-retry#D001(使用显式跳过已完成节点，而非依赖 LangGraph 自动 checkpoint 恢复)

## [0.2.0] - 2026-04-23

### 新增
- **[app]**: 为租户工作流新增 schedule 配置接口与手动触发入口，支持 cron 校验、启停控制和统一响应输出 — by withoctober
  - 方案: [202604230620_tenant-workflow-cron-schedule](plan/202604230620_tenant-workflow-cron-schedule/)
  - 决策: tenant-workflow-cron-schedule#D001(采用数据库驱动的应用内调度器)
- **[runtime]**: 新增数据库驱动的后台调度器，支持按租户和工作流恢复 cron 任务、执行工作流并回写最近/下次执行状态 — by withoctober
  - 方案: [202604230620_tenant-workflow-cron-schedule](plan/202604230620_tenant-workflow-cron-schedule/)
  - 决策: tenant-workflow-cron-schedule#D002(用后台线程轮询替代外部调度依赖)

## [0.1.9] - 2026-04-22

### 新增
- **[workflow]**: 将统一节点日志与失败现场快照推广到 `content_create`、`content_collect`、`daily_report`，为抓取、生成、出图、写库等阶段补充标准化工件落盘能力 — by withoctober
  - 方案: [202604222329_workflow-node-logging-rollout](plan/202604222329_workflow-node-logging-rollout/)
  - 决策: workflow-node-logging-rollout#D001(统一日志能力在公共层抽象)

## [0.1.8] - 2026-04-22

### 新增
- **[runtime]**: 为工作流运行时新增节点内部结构化执行日志，统一落入 `events.jsonl`，可排查节点内部卡点、异常原因与子步骤耗时 — by withoctober
  - 方案: [202604222229_node-internal-execution-logs](plan/202604222229_node-internal-execution-logs/)
  - 决策: node-internal-execution-logs#D001(节点内部日志复用现有 events.jsonl 事件流)

## [0.1.7] - 2026-04-22

### 新增
- **[app]**: 新增 `POST /tenants`，支持仅传租户名称创建租户并自动生成唯一 `tenant_id`，同时补齐文档与测试验证 — by withoctober
  - 方案: [202604222023_tenant-name-only-create](plan/202604222023_tenant-name-only-create/)
  - 决策: tenant-name-only-create#D001(新增 POST 创建入口并保留 PUT 兼容路径)

## [0.1.6] - 2026-04-22

### 快速修改
- **[app]**: 整理 `app.routes` 的导入顺序与统一响应包装缩进，保持行为不变 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/routes.py

## [0.1.5] - 2026-04-22

### 快速修改
- **[app]**: 移除 `app.model` 对 `workflow.integrations.feishu` 常量的依赖，确保 model 对 integrations 零依赖 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/model.py

## [0.1.4] - 2026-04-22

### 修复
- **[integrations]**: 将飞书共享集成能力从 `app.model` 抽离到 `workflow.integrations.feishu`，收敛 model 仅保留数据相关职责 — by withoctober
  - 方案: [202604222002_feishu-integration-extract](archive/2026-04/202604222002_feishu-integration-extract/)

## [0.1.3] - 2026-04-22

### 修复
- **[app]**: 统一所有 API 返回为 HTTP 200 + `code/message/data` 响应结构，并收敛业务异常与参数校验异常输出 — by withoctober
  - 方案: [202604221948_api-unified-response](archive/2026-04/202604221948_api-unified-response/)

## [0.1.2] - 2026-04-22

### 快速修改
- **[app]**: 飞书初始化接口在租户不存在时直接返回 404，避免隐式创建租户并写入飞书配置 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: app/routes.py, tests/test_app_routes.py

## [0.1.1] - 2026-04-21

### 修复
- **[architecture]**: 完成 flow-centric 重构，移除旧的 `graphs/`、`nodes/`、`services/` 平铺入口
  - 类型: 结构优化
  - 方案: [202604211834_langgraph-flow-centric-refactor](plan/202604211834_langgraph-flow-centric-refactor/)

### 快速修改
- **[prompts]**: 统一 content_collect、content_create、daily_report 提示词的顶层结构与标题命名风格 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: flows/content_collect/prompts/topic_bank.md, flows/content_collect/prompts/keyword_matrix.md, flows/content_collect/prompts/industry_keywords.md, flows/content_collect/prompts/industry_report.md, flows/content_create/prompts/original_copy.md, flows/content_create/prompts/original_image.md, flows/content_create/prompts/rewrite_copy.md, flows/content_create/prompts/rewrite_image.md, flows/daily_report/prompts/generate.md
- **[llm]**: 统一 generation 层为“模板原文 + 少量槽位 + template_values 运行时上下文”输入模式，并收敛 prompt 中的长文本模板槽位 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: core/prompting.py, flows/content_collect/generation.py, flows/content_create/generation.py, flows/daily_report/generation.py, flows/content_create/prompts/original_copy.md, flows/content_create/prompts/original_image.md, flows/content_create/prompts/rewrite_copy.md, flows/content_create/prompts/rewrite_image.md, flows/daily_report/prompts/generate.md
- **[prompts]**: 统一 content_collect 组 prompt 的“运行时输入 / 参考资料边界 / 缺失处理”表述，尤其收敛 marketing_plan 的超长输入说明 — by withoctober
  - 类型: 快速修改（无方案包）
  - 文件: flows/content_collect/prompts/topic_bank.md, flows/content_collect/prompts/keyword_matrix.md, flows/content_collect/prompts/industry_keywords.md, flows/content_collect/prompts/industry_report.md, flows/content_collect/prompts/marketing_plan.md
