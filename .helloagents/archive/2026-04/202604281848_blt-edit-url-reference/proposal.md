# 变更提案: blt-edit-url-reference

## 元信息
```yaml
类型: 优化
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-28
```

---

## 1. 需求

### 背景
作品库编辑图片当前会构造最多 8 张参考图并下载后再提交给图片编辑 provider。用户确认 BLT 支持直接传图片 URL，并要求只传当前需要编辑的那一张，避免下载多余参考图导致接口等待时间过长。

### 目标
- BLT 图片编辑只使用当前被编辑的图片 URL。
- BLT 图片编辑请求不下载参考图，不走 multipart 文件上传，直接在请求字段中传 `image=<url>`。
- 不做文件上传回退，BLT URL 模式失败时直接返回错误。
- 保持 OpenAI 图片编辑原有多参考图下载/上传行为不变。

### 约束条件
```yaml
时间约束: 快速修正作品库编辑等待时间
性能约束: BLT 编辑不得下载非必要参考图
兼容性约束: openai provider 行为保持不变
业务约束: 用户明确选择不考虑回退
```

### 验收标准
- [ ] `IMAGE_PROVIDER=blt` 时，作品库编辑参考图列表只包含当前编辑图片 URL。
- [ ] BLT 编辑请求字段包含 `image=<url>`，不包含 multipart 文件体。
- [ ] `edit_image` 对 BLT 不调用 `download_reference_image`。
- [ ] 相关单元测试通过。

---

## 2. 方案

### 技术方案
- 在路由构造参考图时，根据 `runtime_payload` 判断图片 provider；BLT 直接使用 `[selected_image_url]`。
- 在 `workflow.integrations.image_generation` 中新增 BLT URL 编辑请求函数，使用 JSON `POST /images/edits` 并传 `model/prompt/image/response_format`。
- `edit_image` 中 BLT 分支只取第一条 URL，直接调用 URL 编辑请求；OpenAI 分支继续下载参考图并走 SDK。
- 更新测试覆盖路由传参和 BLT URL 请求协议。

### 影响范围
```yaml
涉及模块:
  - app: 作品库编辑图片参考图选择逻辑
  - integrations: BLT 图片编辑请求协议
  - tests: 更新 BLT 编辑测试
预计变更文件: 3
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| BLT URL 编辑接口返回结构变化 | 低 | 复用现有 `data[].url`、`data[].b64_json`、`image_url` 解析 |
| 某些图片 URL 不可被 BLT 访问 | 中 | 按用户选择不回退，错误直接透出 |

---

## 3. 技术设计（可选）

### API设计
#### BLT POST /images/edits
- **请求**: JSON，包含 `model`、`prompt`、`image` URL、可选 `aspect_ratio`、`response_format`
- **响应**: 兼容 `data[].url`、`data[].b64_json` 或顶层 `image_url`

### 数据模型
N/A

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: 作品库 BLT 编辑图片
**模块**: app / integrations
**条件**: 租户或系统配置 `IMAGE_PROVIDER=blt`
**行为**: 作品库编辑接口只传当前编辑图片 URL 给 BLT `/images/edits`
**结果**: 后端不下载多余参考图，BLT 返回结果后上传到 S3 并更新 artifact

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### blt-edit-url-reference#D001: BLT 编辑图使用 URL 直传
**日期**: 2026-04-28
**状态**: ✅采纳
**背景**: 用户确认 BLT 支持图片 URL 输入，并明确选择不考虑回退。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: URL 直传，无回退 | 最少等待，避免下载参考图 | URL 不可访问时直接失败 |
| B: URL 优先，失败回退文件 | 兼容性更强 | 失败路径耗时更长，逻辑更复杂 |
**决策**: 选择方案 A
**理由**: 用户明确回复选项 2，并补充 BLT 支持图片 URL。
**影响**: 影响 BLT provider 的编辑请求协议和作品库编辑参考图选择逻辑。

---

## 6. 成果设计

N/A：本任务为后端接口行为优化，不产生视觉交付物。

### 技术约束
- **可访问性**: N/A
- **响应式**: N/A
