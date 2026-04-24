# 模块: flows

## 职责

- 承载 `content_collect`、`content_create`、`daily_report` 等业务流程定义。
- 通过 `workflow.flow.common` 提供节点级公共 helper，包括输出持久化、阻断/软失败返回、工件写入和内部步骤日志。
- 负责在节点内部关键子步骤记录结构化日志，帮助定位运行卡点和失败原因。
- 通过 `workflow.flow.registry` 集中维护工作流构建器与运行参数 schema 元数据，供 HTTP 列表接口直接复用。

## 行为规范

- 节点开始与结束状态由 runtime 统一记录；节点内部日志由各节点在关键步骤显式补充。
- 工作流注册表除了暴露 `builder` 外，还要为每个 flow 声明 `run_request_schema`，并保持 `build_flow_definition()`、`has_flow_definition()` 等调用接口兼容。
- `run_request_schema` 只暴露该 flow 实际支持的执行参数；字段需包含 `type`、`description`、`default` 与字段级 `required` 标记，schema 顶层维护 `required` 列表。
- 公共 helper 会自动记录以下事件：
  - `step_output`：节点产生输出摘要
  - `artifact_written`：工件文件已写入
  - `blocked`：节点进入阻断状态
  - `soft_failed`：节点进入非阻断失败状态
- 复杂节点应在关键过程记录阶段事件，例如输入装载、外部接口调用、分页抓取、模型生成、写库等，必要时补充耗时与摘要。
- 节点日志只记录摘要信息，不直接写入超大原始 payload，原始内容仍通过工件文件持久化。

## 已接入的关键日志点

- `content_collect`：资料校验、行业关键词生成、行业报告生成、对标账号解析与分页抓取、热点抓取、营销策划方案生成、关键词矩阵生成、选题库生成
- `content_create`：原创/二创文案生成、对标笔记抓取、参考图解析、图片提示词生成、图片生成、生成图转存 S3、作品库写入
- `content_create`：原创/二创文案生成、对标笔记抓取、参考图解析、图片提示词生成、图片生成、生成图转存 S3、作品库写入，并将最终创作结果同步写入 `artifacts` 业务表
- `daily_report`：依赖装载、日报生成、日报写入

## 依赖关系

- 依赖 `workflow.runtime` 提供运行上下文和事件日志写入能力。
- 依赖 `workflow.core` 提供模型调用、消息追踪与文本截断。
- 依赖 `workflow.store` 和 `workflow.integrations` 访问外部数据源及第三方接口。
- 被 `app.routes` 通过 `GraphRuntime.list_flows()` 间接复用，用于生成工作流列表返回结构。
