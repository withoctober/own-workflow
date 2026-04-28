# 变更提案: remove-blt-image-provider

## 元信息
```yaml
类型: 回滚
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-28
```

---

## 1. 需求

### 背景
用户要求回退并移除 `blt` 图片 provider。保留现有 `IMAGE_PROVIDER` / `IMAGE_API_*` 统一配置体系，以及 `ark`、`openai` 两条 provider 路径。

### 目标
- 移除运行时 `blt` provider 分支与请求函数。
- 移除 BLT 相关单元测试。
- 文档和示例不再推荐或声明 `IMAGE_PROVIDER=blt`。
- 保留 `ark` 和 `openai` 的图片生成/编辑行为。

### 约束条件
```yaml
时间约束: 快速回退
性能约束: N/A
兼容性约束: 不影响 ark/openai
业务约束: 只移除 blt provider，不回退 IMAGE_API_* 统一配置
```

### 验收标准
- [ ] `IMAGE_PROVIDER=blt` 不再被识别为支持的 provider。
- [ ] `workflow.integrations.image_generation` 中不存在 BLT 请求函数和分发分支。
- [ ] 作品库编辑不再包含 BLT 特判。
- [ ] 图片集成层和路由测试通过。

---

## 2. 方案

### 技术方案
- 删除 `SUPPORTED_IMAGE_PROVIDERS` 中的 `blt`。
- 删除 `request_blt_image`、`request_blt_image_edit`、`request_blt_image_edit_from_url` 及相关 multipart helper 的运行时使用。
- 删除 `app.routes` 中基于 BLT 的单图 URL 特判，恢复统一参考图构造逻辑。
- 删除 BLT 相关测试用例和导入。
- 更新 `.env.example`、README、api 文档和知识库模块说明。

### 影响范围
```yaml
涉及模块:
  - integrations: 删除 BLT provider
  - app: 删除 BLT 作品库编辑特判
  - tests: 删除 BLT 测试
  - docs: 删除 BLT provider 说明
预计变更文件: 7
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 误删 openai/ark 逻辑 | 中 | 运行相关单元测试验证 |
| 文档仍残留 blt 示例 | 低 | 搜索运行时代码和文档残留 |

---

## 3. 技术设计（可选）

N/A：本次为 provider 移除，不新增 API。

### 数据模型
N/A

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: 不支持 BLT provider
**模块**: integrations
**条件**: 调用方配置 `IMAGE_PROVIDER=blt`
**行为**: 图片集成层按不支持 provider 处理
**结果**: 返回 `unsupported image provider: blt`

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### remove-blt-image-provider#D001: 移除 BLT provider
**日期**: 2026-04-28
**状态**: ✅采纳
**背景**: 用户明确要求“回退，移除 blt provider”，并确认只移除 BLT。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 只移除 BLT | 风险低，不影响现有 IMAGE_API_* 和 ark/openai | 历史归档记录仍会保留 BLT 文字 |
| B: 全量回退图片配置 | 可回到更早状态 | 影响范围大，可能误伤已完成配置统一 |
**决策**: 选择方案 A
**理由**: 用户选择选项 1；目标是移除 `blt` provider，而不是撤销图片配置统一。
**影响**: 影响 integrations、app、tests、docs 和知识库当前说明。

---

## 6. 成果设计

N/A：后端 provider 移除任务，无视觉交付物。

### 技术约束
- **可访问性**: N/A
- **响应式**: N/A
