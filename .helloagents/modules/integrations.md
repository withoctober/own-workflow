# 模块: integrations

## 职责

- 承载项目对第三方系统的共享集成能力。
- 提供可被 `app` 与 `workflow` 其他模块复用的外部系统适配逻辑。
- 当前包含热点抓取与通用 S3 上传能力。

## 行为规范

- 通用对象存储上传逻辑统一收敛在 `workflow.integrations.s3`，提供 `upload_bytes()` 与 `upload_from_url()` 两个复用入口。
- TikHub 热点抓取与内容抓取、Ark 生图、LLM 配置支持从租户运行时配置读取自定义 API 值；S3 上传始终读取系统环境变量或项目根目录 `.env`。
- `integrations` 层不负责租户配置的数据库持久化；持久化由 `app.model` 负责。
- 公共集成能力需要在 `workflow.integrations.__init__` 暴露，便于调用方稳定导入。

## 依赖关系

- 依赖 `workflow.store.*` 或其他外部访问实现与第三方系统通信。
- 被 `app.routes` 与 workflow 内其他模块复用。
