# 变更提案: flow-list-required-params

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已完成
创建: 2026-04-24
```

---

## 1. 需求

### 背景
前端当前只能从 `GET /api/flows` 获取工作流 `id`，无法知道某个工作流执行时是否需要额外输入参数。
而 `POST /api/flows/{flow_id}/runs` 的参数要求目前只分散在后端 schema 描述和业务语义中，
导致前端需要写死规则，不利于后续扩展。

### 目标
让工作流列表接口在返回每个 flow 时，同时返回一份完整的 `run_request_schema`，
用于告诉前端该工作流执行时可传哪些参数，并标明每个参数是必填还是选填。

### 约束条件
```yaml
时间约束: 无
性能约束: 列表接口不引入额外运行时扫描或动态计算
兼容性约束:
  - 保留现有 `flows[].id` 返回结构
  - 新增字段为向后兼容扩展
业务约束:
  - 按用户最新要求，返回完整运行参数 schema，而不是仅返回必填字段名列表
  - schema 需要标明字段类型、描述、默认值，以及必填/选填状态
  - 前端能直接根据 schema 生成执行参数输入表单
```

### 验收标准
- [ ] `GET /api/flows` 的每个工作流条目包含 `run_request_schema`
- [ ] `content-create-rewrite` 的 schema 将 `source_url` 标记为必填
- [ ] 其他 flow 的 schema 正确标记可用参数与选填字段
- [ ] 测试与 API 文档同步更新

---

## 2. 方案

### 技术方案
在 `workflow/flow/registry.py` 中把工作流注册信息从单纯的 builder 映射升级为包含
`builder` 与 `run_request_schema` 的元数据映射，并保持 `build_flow_definition()`、
`has_flow_definition()` 等调用接口不变。`GraphRuntime.list_flows()` 继续透传注册表定义，
从而让 `/api/flows` 自动返回 `id + run_request_schema`。schema 采用 object/properties/required
结构，每个字段附带 `type`、`description`、`default` 与字段级 `required` 标记。
同时补齐注册表测试、路由测试和文档说明。

### 影响范围
```yaml
涉及模块:
  - workflow.flow.registry: 暴露工作流运行参数 schema 元数据
  - app.routes: 列表接口返回结构随注册表扩展
  - tests: 覆盖返回结构与具体 flow 参数约束
  - docs: 更新 README 与 api.md 示例
预计变更文件: 6
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 列表接口返回结构变化影响现有调用方 | 低 | 仅新增字段，不移除既有 `id` |
| 错误标记某个 flow 的参数必填性 | 中 | 用注册表集中维护并补测试 |
| 文档与实际返回结构不一致 | 中 | 同步更新 README、api.md 与知识库 |

---

## 3. 技术设计（可选）

> 涉及架构变更、API设计、数据模型变更时填写

### API设计
#### GET /api/flows
- **请求**: 无请求体，仍要求 `X-API-Key`
- **响应**:
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "flows": [
      {
        "id": "content-collect",
        "run_request_schema": {
          "type": "object",
          "properties": {
            "tenant_id": {
              "type": "string",
              "required": false
            },
            "batch_id": {
              "type": "string",
              "required": false
            }
          },
          "required": []
        }
      },
      {
        "id": "content-create-rewrite",
        "run_request_schema": {
          "type": "object",
          "properties": {
            "tenant_id": {
              "type": "string",
              "required": false
            },
            "batch_id": {
              "type": "string",
              "required": false
            },
            "source_url": {
              "type": "string",
              "required": true
            }
          },
          "required": ["source_url"]
        }
      }
    ]
  }
}
```

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: 前端渲染工作流执行表单
**模块**: API / Flow Registry
**条件**: 前端调用 `GET /api/flows` 获取工作流列表
**行为**: 后端返回每个工作流的 `id` 和 `run_request_schema`
**结果**: 前端根据 schema 渲染输入项，并判断哪些字段必须填写

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### flow-list-required-params#D001: 返回完整运行参数 schema
**日期**: 2026-04-24
**状态**: ✅采纳
**背景**: 前端不仅需要知道“哪些参数必须输入”，还需要字段类型、默认值和描述来生成执行表单。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 返回 `required_params` 数组 | 结构最小 | 前端仍需自己维护字段描述、类型与默认值 |
| B: 返回完整参数 schema | 前端可直接生成表单，扩展性更好 | 返回结构更长 |
**决策**: 选择方案 B
**理由**: 用户已明确要求完整 schema，并要求区分必填和选填
**影响**: 影响 flow 注册表、列表接口、测试和 API 文档

---

## 6. 成果设计

> 含视觉产出的任务由 DESIGN Phase2 填充。非视觉任务整节标注"N/A"。

N/A。本任务无视觉产出。
