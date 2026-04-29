# 任务清单: image-api-config

> **@status:** completed | 2026-04-28 18:02

```yaml
@feature: image-api-config
@created: 2026-04-28
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 4 | 0 | 0 | 4 |

---

## 任务列表

### 1. 图片配置解析

- [√] 1.1 在 `workflow/integrations/image_generation.py` 中将图片 provider/base_url/key/model 收敛为 `IMAGE_PROVIDER`、`IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL` | depends_on: []
- [√] 1.2 在 `app/routes.py` 与 `workflow/flow/content_create/nodes.py` 中移除图片 provider/model 硬编码 | depends_on: [1.1]

### 2. 文档与测试

- [√] 2.1 更新 `.env.example`、README 和 api 文档中的图片配置说明 | depends_on: [1.1]
- [√] 2.2 更新并运行图片生成相关测试 | depends_on: [1.1, 1.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-28 17:58 | 1.1 | completed | 图片配置解析统一到 `IMAGE_PROVIDER` 与 `IMAGE_API_*` |
| 2026-04-28 17:58 | 1.2 | completed | 移除业务调用中的图片 provider/model 硬编码 |
| 2026-04-28 17:59 | 2.1 | completed | 更新 `.env.example`、README、api.md 与知识库 |
| 2026-04-28 18:00 | 2.2 | completed | 相关测试和语法检查通过 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

## LIVE_STATUS

```json
{"status":"completed","completed":4,"failed":0,"pending":0,"total":4,"done":4,"percent":100,"current":"图片配置统一迁移完成","updated_at":"2026-04-28 18:00:00"}
```

## 验证记录

- `uv run python -m py_compile app/routes.py app/schemas.py workflow/integrations/image_generation.py workflow/flow/content_create/nodes.py tests/test_content_create_images.py tests/test_app_routes.py`
- `uv run python -m unittest tests.test_content_create_images tests.test_app_routes.AppRoutesTest.test_post_tenant_creates_tenant_with_generated_id tests.test_app_routes.AppRoutesTest.test_post_tenant_rejects_incomplete_api_ref_for_custom_mode tests.test_app_routes.AppRoutesTest.test_regenerate_artifact_image_uses_edit_mode_with_reference_images`
- `uv run python -m unittest discover -s tests` 已执行，存在与本次变更无关的既有失败：`fake-flow/test-flow` 注册相关错误、`test_app_model` JSON 参数断言、`test_store_database` 字段断言。
