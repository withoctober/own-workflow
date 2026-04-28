# 任务清单: uni-image-provider

```yaml
@feature: uni-image-provider
@created: 2026-04-28
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 5 | 0 | 0 | 5 |

---

## 任务列表

### 1. 集成实现

- [√] 1.1 在 `workflow/integrations/image_generation.py` 中新增 `uni` provider 配置解析、生成请求、编辑请求和响应解析 | depends_on: []
- [√] 1.2 将 `generate_images()` 与 `edit_image()` 分发接入 UniProvider，保持 `ark` 与 `openai` 行为不变 | depends_on: [1.1]

### 2. 测试与文档

- [√] 2.1 更新 `tests/test_content_create_images.py` 覆盖 UniAPI 生图、改图、multipart `image[]` 字段和 base64 上传 | depends_on: [1.2]
- [√] 2.2 更新 `.env.example`、`README.md`、`api.md` 与 `helloagents/modules/integrations.md` 的 provider 说明 | depends_on: [1.2]
- [√] 2.3 运行相关单元测试，并用当前 UniAPI 端点做一次真实请求验证 | depends_on: [2.1, 2.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-28 20:39 | 方案包创建 | pending | 用户确认使用 `IMAGE_PROVIDER=uni` 并复用 `IMAGE_API_*` 配置 |
| 2026-04-28 20:55 | 开发实施 | completed | UniAPI 生图和编辑单测通过，真实生成与编辑请求均通过并上传 S3 |

---

## LIVE_STATUS

```json
{"status":"completed","completed":5,"failed":0,"pending":0,"total":5,"done":5,"percent":100,"current":"已完成","updated_at":"2026-04-28 20:55:00"}
```

---

## 执行备注

> 用户提供并验证的 UniAPI 协议：生成接口 `POST /images/generations` 使用 JSON；编辑接口 `POST /images/edits` 使用 multipart 字段 `image[]=@file`；两者均解析 `data[0].b64_json`。
