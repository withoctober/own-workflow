# 变更提案: image-api-config

## 元信息
```yaml
类型: 重构
方案类型: implementation
优先级: P1
状态: 执行中
创建: 2026-04-28
```

---

## 1. 需求

### 背景
当前图片生成配置同时读取 `OPENAI_IMAGE_*`、`OPENAI_*`、`ARK_*` 和 `step` 覆盖项，容易让文本 LLM 配置影响生图请求。用户要求图片配置改为新的统一变量，并同时支持租户级 `api_ref` 与环境变量。

### 目标
- 图片 provider 统一由 `IMAGE_PROVIDER` 决定。
- 图片 API base URL、API key、模型统一由 `IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL` 决定。
- 租户 `api_ref` 与系统 `.env` 均支持上述同名 key，租户 custom 模式优先。
- 不兼容旧的 `OPENAI_IMAGE_*`、`OPENAI_*`、`ARK_*` 图片配置。
- 去除业务调用中硬编码图片 provider/model/base_url 的路径，让配置来源保持一致。

### 约束条件
```yaml
时间约束: 无
性能约束: 不改变现有同步调用与上传行为
兼容性约束: 不保留旧图片配置变量兼容
业务约束: 文本 LLM 配置仍继续使用 `OPENAI_*`
```

### 验收标准
- [ ] OpenAI 图片生成和编辑只读取 `IMAGE_API_*` 与 `IMAGE_PROVIDER`
- [ ] Ark 图片生成也通过统一 `IMAGE_API_KEY`/`IMAGE_API_MODEL` 获取凭证和模型
- [ ] 文档和 `.env.example` 展示新变量
- [ ] 相关图片生成测试通过

---

## 2. 方案

### 技术方案
在 `workflow.integrations.image_generation` 中收敛图片配置解析函数：provider 读取 `IMAGE_PROVIDER`，API key 读取 `IMAGE_API_KEY`，base URL 读取 `IMAGE_API_BASE_URL`，模型读取 `IMAGE_API_MODEL`。业务层调用 `generate_images`/`edit_image` 时不再在 `step` 中硬编码 provider/model。同步更新 `.env.example`、README、api 文档和单元测试。

### 影响范围
```yaml
涉及模块:
  - workflow.integrations.image_generation: 图片配置解析
  - workflow.flow.content_create.nodes: 去除图片配置硬编码
  - app.routes: 作品库重生成使用统一配置
  - tests: 更新图片配置测试
  - docs/env: 更新配置说明
预计变更文件: 6-8
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 现有环境仍使用旧变量导致生图失败 | 中 | `.env.example` 和文档明确迁移到新变量 |
| Ark 与 OpenAI 使用同名 key 语义变化 | 低 | `IMAGE_PROVIDER` 决定当前 provider，`IMAGE_API_*` 表示当前图片 provider 的配置 |

---

## 3. 技术设计（可选）

N/A

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: OpenAI 图片编辑
**模块**: `workflow.integrations.image_generation`
**条件**: 租户 `api_mode=custom` 的 `api_ref` 或 `.env` 配置了 `IMAGE_PROVIDER=openai`、`IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL`
**行为**: 作品库重生成调用 `edit_image`，解析统一图片配置后请求 `client.images.edit`
**结果**: 不读取旧 `OPENAI_IMAGE_*` 或 `OPENAI_*` 图片配置。

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### image-api-config#D001: 图片配置统一为 IMAGE_API_* 变量
**日期**: 2026-04-28
**状态**: ✅采纳
**背景**: 生图和文本模型配置混用会导致 base URL、key、model 难以判断实际来源。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 新变量优先，旧变量 fallback | 平滑迁移 | 仍可能被旧 `OPENAI_BASE_URL` 误影响 |
| B: 只支持新变量 | 行为清晰，符合用户要求 | 需要同步更新部署环境 |
**决策**: 选择方案 B
**理由**: 用户明确要求不兼容旧变量，完全按照新变量执行。
**影响**: 图片生成/编辑配置、租户 `api_ref`、部署环境变量和文档示例。

---

## 6. 成果设计

N/A
