# CHANGELOG

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
