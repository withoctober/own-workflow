# 模块: integrations

## 职责

- 承载项目对第三方系统的共享集成能力。
- 提供可被 `app` 与 `workflow` 其他模块复用的外部系统适配逻辑。
- 当前包含热点抓取、图片生成与通用 S3 上传能力。

## 行为规范

- 通用对象存储上传逻辑统一收敛在 `workflow.integrations.s3`，提供 `upload_bytes()` 与 `upload_from_url()` 两个复用入口。
- TikHub 热点抓取与内容抓取、LLM 配置支持从租户运行时配置读取自定义 API 值；S3 上传始终读取系统环境变量或项目根目录 `.env`。
- 图片生成统一通过 `workflow.integrations.image_generation` 读取 `IMAGE_PROVIDER`、`IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL`；租户 `api_mode=custom` 时优先读取租户 `api_ref` 中的同名 key，否则读取系统环境变量或项目根目录 `.env`。
- 图片 provider 当前支持 `ark`、`openai` 与 `uni`。`openai` provider 通过 OpenAI SDK 支持普通生成与图片编辑；`uni` provider 通过 UniAPI JSON `/images/generations` 和 multipart `image[]` `/images/edits` 支持普通生成与图片编辑；`ark` provider 支持普通生成。
- `generate_images()` 会在调用 provider 前逐项校验 prompt 列表；任意提示词为空时直接抛出本地错误，不向远端图片接口发送无效请求，也不通过过滤导致图片槽位错位。
- `integrations` 层不负责租户配置的数据库持久化；持久化由 `app.model` 负责。
- 公共集成能力需要在 `workflow.integrations.__init__` 暴露，便于调用方稳定导入。

## 依赖关系

- 依赖 `workflow.store.*` 或其他外部访问实现与第三方系统通信。
- 被 `app.routes` 与 workflow 内其他模块复用。
