# 任务清单: blt-image-provider

> **@status:** completed | 2026-04-28 18:33

```yaml
@feature: blt-image-provider
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

### 1. 图片集成层

- [√] 1.1 在 `workflow/integrations/image_generation.py` 中新增 `blt` provider 分发、JSON 生图请求和 multipart 改图请求 | depends_on: []
- [√] 1.2 在 `workflow/integrations/image_generation.py` 中扩展 BLT 响应解析和 S3 上传源提取 | depends_on: [1.1]

### 2. 配置与文档

- [√] 2.1 更新 `app/schemas.py`、`.env.example`、`README.md`、`api.md`，说明 `IMAGE_PROVIDER=blt` 复用 `IMAGE_API_*` | depends_on: [1.1]

### 3. 测试验证

- [√] 3.1 更新 `tests/test_content_create_images.py` 覆盖 BLT 生成、编辑与响应解析 | depends_on: [1.1, 1.2]
- [√] 3.2 运行相关测试并完成验收 | depends_on: [3.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-28 18:29:33 | 方案包创建 | completed | 已确认按用户提供 BLT API 调用方式实现 |
| 2026-04-28 18:32:40 | 开发实施 | completed | 已新增 BLT provider、文档和测试，相关测试通过 |

## LIVE_STATUS

```json
{"status":"completed","completed":5,"failed":0,"pending":0,"total":5,"done":5,"percent":100,"current":"已完成","updated_at":"2026-04-28 18:32:40"}
```

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

用户明确要求按其提供的 BLT API 调用方式实现：生成走 `/images/generations` JSON，编辑走 `/images/edits` multipart，不使用 OpenAI SDK。
