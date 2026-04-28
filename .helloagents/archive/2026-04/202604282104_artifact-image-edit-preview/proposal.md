# 变更提案: artifact-image-edit-preview

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
作品库现有 `POST /api/artifacts/{artifact_id}/regenerate-image` 接口会在图片编辑生成成功后立即调用 `update_artifact`，直接替换 `cover_url` 或 `image_urls`。前端需要先生成编辑预览，用户确认保存后再通过现有 artifact 更新能力替换图片，避免“未保存也已替换”的副作用。

### 目标
新增一个无持久化副作用的作品库图片编辑预览接口：

- 复用现有作品图片编辑参考图、提示词回退和租户运行配置逻辑。
- 返回生成后的图片 URL、目标图片索引和实际使用的 prompt。
- 不调用 `update_artifact`，不修改 `artifacts` 表。
- 保持现有 `regenerate-image` 立即保存接口兼容。

### 约束条件
```yaml
时间约束: 本次迭代内完成
性能约束: 复用现有图片编辑调用链，不额外增加数据库写入
兼容性约束: 不改变 regenerate-image 的外部语义
业务约束: 预览接口仅生成图片，不代表用户已保存作品变更
```

### 验收标准
- [ ] `POST /api/artifacts/{artifact_id}/preview-image-edit` 返回 `generated_url`、`image_index`、`prompt`。
- [ ] 预览接口调用图片编辑集成，但不调用 `update_artifact`。
- [ ] 预览接口沿用现有鉴权、租户配置、artifact 存在性、图片索引和 prompt 校验。
- [ ] 现有 `regenerate-image` 接口仍会生成并保存替换后的 artifact 图片字段。
- [ ] 路由测试覆盖预览接口无持久化副作用。

---

## 2. 方案

### 技术方案
在 `app.routes` 中抽取共享 helper `_generate_artifact_image_edit_preview()`，集中处理：

- 根据 `image_index` 定位封面或配图槽位。
- 解析实际使用的 prompt。
- 构造参考图列表。
- 调用 `edit_image()` 并解析 `generated_url`。

新增 `POST /api/artifacts/{artifact_id}/preview-image-edit` 路由。该路由完成鉴权、租户和 artifact 查询后调用共享 helper，只返回预览结果，不调用 `update_artifact`。

现有 `regenerate-image` 路由改为复用同一个 helper，然后继续执行原有字段替换和 `update_artifact` 持久化逻辑，避免两条路径的图片编辑行为分叉。

### 影响范围
```yaml
涉及模块:
  - app: 新增图片编辑预览请求模型和路由
  - tests: 增加预览接口无持久化副作用测试
预计变更文件: 3
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 前端误用旧接口仍会立即保存 | 中 | 保留旧接口语义，新增明确的预览接口供前端切换 |
| 共享 helper 改动影响旧接口 | 中 | 增加路由测试并运行现有 regenerate-image 测试 |
| 预览接口暴露过多内部信息 | 低 | 响应只返回 `generated_url`、`image_index`、`prompt` |

---

## 3. 技术设计

### API 设计
#### POST `/api/artifacts/{artifact_id}/preview-image-edit`
- **请求**:
```json
{
  "image_index": 1,
  "prompt": "可选图片编辑提示词"
}
```
- **响应**:
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "generated_url": "https://cdn.example.com/preview.png",
    "image_index": 1,
    "prompt": "实际使用的提示词"
  }
}
```

### 数据模型
不新增数据库字段，不修改 artifact 表结构。

---

## 4. 核心场景

### 场景: 作品图片编辑预览
**模块**: app
**条件**: 当前租户已鉴权，artifact 存在，目标图片槽位和 prompt 有效。  
**行为**: 前端调用 `POST /api/artifacts/{artifact_id}/preview-image-edit`。  
**结果**: 服务端返回生成图片 URL；artifact 原有 `cover_url` 和 `image_urls` 保持不变。

### 场景: 用户确认后保存图片替换
**模块**: app
**条件**: 前端已拿到预览图 URL，用户确认保存。  
**行为**: 前端调用现有 `PUT /api/artifacts/{artifact_id}` 提交新的 `cover_url` 或 `image_urls`。  
**结果**: artifact 图片字段按显式保存请求更新。

---

## 5. 技术决策

### artifact-image-edit-preview#D001: 新增独立预览接口
**日期**: 2026-04-28  
**状态**: ✅采纳  
**背景**: 现有 `regenerate-image` 是立即保存接口，直接改默认行为会破坏既有调用方。  
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 新增 `preview-image-edit` | 语义清晰，不影响旧接口；前端可显式区分预览与保存 | 需要前端改为调用新接口 |
| B: 给 `regenerate-image` 增加 `save=false` | 单接口复用 | 默认值和兼容语义容易混淆 |
| C: 预览接口返回完整 artifact | 前端保存时上下文完整 | 响应更重，容易误以为已经保存 |
**决策**: 选择方案 A。  
**理由**: 最小化兼容风险，并让 API 语义与用户操作一致。  
**影响**: `app.routes`、`app.schemas` 和路由测试。

---

## 6. 成果设计

N/A。后端 API 变更，不包含视觉产出。
