# 任务清单: artifact-image-edit-preview

> **@status:** completed | 2026-04-28 21:11

```yaml
@feature: artifact-image-edit-preview
@created: 2026-04-28
@status: in_progress
@mode: R2
```

## LIVE_STATUS

```json
{"status":"in_progress","completed":3,"failed":0,"pending":0,"total":3,"done":3,"percent":100,"current":"路由测试通过，准备归档方案包","updated_at":"2026-04-28 21:12:00"}
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 3 | 0 | 0 | 3 |

---

## 任务列表

### 1. API 实现

- [√] 1.1 在 `app/schemas.py` 中新增图片编辑预览请求模型 | depends_on: []
- [√] 1.2 在 `app/routes.py` 中抽取图片编辑生成共享逻辑并新增 `preview-image-edit` 路由 | depends_on: [1.1]

### 2. 验证

- [√] 2.1 在 `tests/test_app_routes.py` 中增加预览接口测试，确认不调用 `update_artifact` | depends_on: [1.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-28 21:04 | 方案设计 | completed | 已确定新增独立预览接口，保持旧保存接口兼容 |
| 2026-04-28 21:08 | 1.1 | completed | 新增 `ArtifactPreviewImageEditRequest` |
| 2026-04-28 21:09 | 1.2 | completed | 新增 `preview-image-edit`，旧保存接口复用共享 helper |
| 2026-04-28 21:10 | 2.1 | completed | 增加无持久化副作用测试 |
| 2026-04-28 21:12 | 验证 | completed | 定向路由测试通过 |

---

## 执行备注

- 本次变更为后端 API 局部新增，TASK_COMPLEXITY=simple。
- 知识库存在，KB_SKIPPED=false，开发完成后同步 `modules/app.md` 与 `CHANGELOG.md`。
