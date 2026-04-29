# 变更提案: uni-image-provider

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-28
```

---

## 1. 需求

### 背景
当前图片集成层支持 `ark` 与 `openai` provider。用户已经通过 curl 验证 UniAPI 的图片编辑接口可用，但它需要使用 UniAPI 的协议形态：编辑接口 `POST /images/edits` 使用 multipart 字段 `image[]=@file`，生成接口 `POST /images/generations` 使用 JSON，并从 `data[0].b64_json` 读取图片数据。现有 `openai` provider 走 OpenAI SDK，无法直接表达该 multipart 字段格式。

### 目标
- 新增 `IMAGE_PROVIDER=uni` 对应的 UniProvider。
- UniProvider 复用现有 `IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_API_MODEL` 配置。
- UniProvider 图片生成请求 `POST {base_url}/images/generations`，JSON body 包含 `model` 与 `prompt`，解析 `data[].b64_json`。
- UniProvider 图片编辑请求 `POST {base_url}/images/edits`，multipart form 包含 `model`、`prompt`、`image[]` 多文件字段，解析 `data[].b64_json`。
- 生成/编辑结果继续复用现有 S3 上传链路，输出 `cover_url`、`image_urls`、`raw_results`。

### 约束条件
```yaml
兼容性约束: 不改变 ark 与 openai provider 的现有行为
配置约束: 采用 IMAGE_PROVIDER=uni，复用 IMAGE_API_* 配置，不新增 UNI_* 配置
依赖约束: 优先使用标准库构造 UniAPI 请求，不引入新运行时依赖
业务约束: 图片编辑继续支持多张参考图，且去重逻辑保持不变
```

### 验收标准
- [ ] `IMAGE_PROVIDER=uni` 时，`generate_images()` 调用 UniAPI `/images/generations` JSON 接口并上传返回的 base64 图片。
- [ ] `IMAGE_PROVIDER=uni` 时，`edit_image()` 调用 UniAPI `/images/edits` multipart 接口，字段名为 `image[]`，并上传返回的 base64 图片。
- [ ] `ark` 与 `openai` provider 的现有单元测试继续通过。
- [ ] 文档与知识库说明 `uni` provider 及 `IMAGE_API_*` 配置方式。

---

## 2. 方案

### 技术方案
在 `workflow.integrations.image_generation` 中把 `uni` 加入 provider 分发。保留现有 `openai` SDK provider，新增 UniAPI 专用请求函数：

- `request_uni_image(api_key, base_url, payload)`：标准库 JSON POST 到 `/images/generations`。
- `request_uni_image_edit(api_key, base_url, payload, reference_images)`：标准库 multipart/form-data POST 到 `/images/edits`，每张参考图以 `image[]` 字段提交。
- UniAPI 响应统一整理为当前上传链路可识别的 `_sdk_result` 等价结构或直接可提取的 bytes source。
- `extract_generated_sources()` 增加 `uni` 分支，解码 `b64_json` 为 bytes source。

### 影响范围
```yaml
涉及模块:
  - workflow.integrations.image_generation: 新增 uni provider 请求、响应解析与分发
  - tests: 增加 UniAPI 生图和改图单元测试
  - docs: 更新 .env.example、README、api.md 中的 provider 说明
  - helloagents/modules/integrations.md: 同步 provider 支持范围
预计变更文件: 6-7
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| multipart 表单拼接格式与 UniAPI 预期不一致 | 中 | 按用户验证成功的 curl 协议实现并用测试断言字段名 `image[]` |
| UniAPI 返回结构变化 | 低 | 解析 `data[].b64_json`，对缺失结果继续抛出已有 `StoreError` |
| 与 openai provider 行为混淆 | 低 | 新增 `uni` provider 独立分支，不改 `openai` SDK provider |

---

## 3. 技术设计

### 架构设计
```mermaid
flowchart TD
    A[generate_images/edit_image] --> B{IMAGE_PROVIDER}
    B --> C[ark]
    B --> D[openai SDK]
    B --> E[uni]
    E --> F[/images/generations JSON]
    E --> G[/images/edits multipart image[]]
    F --> H[decode b64_json]
    G --> H
    H --> I[S3 upload bytes]
```

### API设计
#### UniAPI POST /images/generations
- **请求**: JSON `{ "model": "gpt-image-2", "prompt": "..." }`
- **响应**: JSON `data[].b64_json`

#### UniAPI POST /images/edits
- **请求**: multipart form `model`, `prompt`, `image[]=@file`
- **响应**: JSON `data[].b64_json`

### 数据模型
不新增数据库字段。

---

## 4. 核心场景

### 场景: UniAPI 图片生成
**模块**: integrations
**条件**: 租户 `api_ref` 或 `.env` 配置 `IMAGE_PROVIDER=uni`、`IMAGE_API_KEY`、`IMAGE_API_BASE_URL`、`IMAGE_API_MODEL`
**行为**: `generate_images()` 向 `{IMAGE_API_BASE_URL}/images/generations` 发送 JSON 请求
**结果**: 解码 `data[].b64_json`，上传到 S3，并返回 artifact 可用的图片 URL

### 场景: UniAPI 图片编辑
**模块**: integrations
**条件**: `edit_image()` 收到一张或多张参考图 URL，provider 为 `uni`
**行为**: 先下载参考图，再向 `{IMAGE_API_BASE_URL}/images/edits` 发送 multipart 请求，每张图使用 `image[]` 字段
**结果**: 解码 `data[].b64_json`，上传到 S3，并返回重生成后的图片 URL

---

## 5. 技术决策

### uni-image-provider#D001: UniProvider 复用 IMAGE_API_* 配置
**日期**: 2026-04-28
**状态**: ✅采纳
**背景**: 用户要求“增加一个 UniProvider”，并选择使用 `IMAGE_PROVIDER=uni` 复用现有 `IMAGE_API_*` 配置入口。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: `IMAGE_PROVIDER=uni` + `IMAGE_API_*` | provider 边界清晰，不破坏 openai SDK 行为，配置体系统一 | 需要新增一个 provider 分支 |
| B: 复用 `IMAGE_PROVIDER=openai` 并改 SDK 行为 | 配置项少 | 会改变现有 openai provider 语义，风险较高 |
| C: 新增 `UNI_*` 配置 | 完全隔离 | 配置体系膨胀，与用户选择不符 |
**决策**: 选择方案 A
**理由**: 符合用户确认的选项 1，同时保持现有 provider 的兼容性。
**影响**: 影响图片集成层、测试与配置文档。

---

## 6. 成果设计

N/A。本任务无视觉 UI 交付物。
