# 变更提案: workflow-runtime-config-injection

## 元信息
```yaml
类型: 重构
方案类型: implementation
优先级: P1
状态: 进行中
创建: 2026-04-22
```

---

## 1. 需求

### 背景
当前 `workflow` 层直接依赖 `app.settings`、`app.model`、`app.utils`，并在多个节点中通过 `runtime.store()` 反复构建 store。每次构建 store 都会重新查询 PostgreSQL 获取租户飞书配置，导致运行期出现不必要的跨层耦合和中途数据库断连风险。

### 目标
- `workflow` 不再依赖 `app` 包
- 租户运行配置由 `app` 层在执行前查询一次 PostgreSQL 后注入 `workflow`
- 单次 run 中后续节点复用已注入的租户运行配置，不再从 `workflow` 内部回查 PostgreSQL

### 约束条件
```yaml
时间约束: 无
性能约束: 不改变现有节点业务行为
兼容性约束: 保持现有 HTTP API 入参不变
业务约束: 仅调整配置解析与注入链路，不改内容收集流程的业务语义
```

### 验收标准
- [ ] `workflow/` 内不再直接 import `app.*`
- [ ] `POST /flows/{flow_id}/runs` 在进入 `workflow` 前完成一次 PostgreSQL 租户配置查询
- [ ] 单次 run 内节点通过注入配置构建 store，不再在 `workflow` 内部回查 PostgreSQL
- [ ] 相关测试通过

---

## 2. 方案

### 技术方案
- 新增 `workflow.settings.WorkflowSettings` 和 `workflow.jsonfile`，替代 `workflow` 对 `app.settings`、`app.utils` 的依赖
- 新增 `workflow.runtime.tenant.TenantRuntimeConfig`，作为 app 注入到 workflow 的租户运行配置载体
- `app.routes.run_flow` 在执行前调用 `get_feishu_runtime_config(...)` 查询 PostgreSQL，并将结果包装为 `TenantRuntimeConfig` 注入 `RunRequest`
- `RuntimeContext` 持有 `tenant_runtime_config`，`runtime.store()` 仅基于该注入配置构建 `FeishuStore`
- `workflow.store.factory` 不再依赖 `app.model` 或数据库访问逻辑，仅消费注入配置

### 影响范围
```yaml
涉及模块:
  - app: run_flow 入口提前解析租户运行配置并注入 workflow
  - workflow.runtime: 接收并传播注入后的运行配置
  - workflow.store: 仅消费注入配置构建 store
  - tests: 增加运行配置注入路径测试
预计变更文件: 10
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 注入链路改造导致运行入口失效 | 中 | 补接口测试和 runtime smoke test |
| store 构建缺少配置时报错路径变化 | 低 | 保留明确错误信息，要求 app 层注入 |

---

## 4. 核心场景

### 场景: 运行前注入租户配置
**模块**: app / workflow.runtime / workflow.store
**条件**: 用户通过 `POST /flows/{flow_id}/runs` 发起一次流程运行
**行为**: app 层先查询 PostgreSQL 获取 tenant 对应的运行配置，再将该配置注入 `RunRequest -> RuntimeContext`
**结果**: workflow 节点执行过程中仅消费注入配置，不再直接访问 PostgreSQL

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### workflow-runtime-config-injection#D001: 租户运行配置在 app 层预解析后注入 workflow
**日期**: 2026-04-22
**状态**: ✅采纳
**背景**: workflow 当前承担了 app 层的租户配置解析职责，并在节点执行中多次回查 PostgreSQL，造成分层污染和运行时脆弱性。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 在 workflow 内缓存首次查询结果 | 改动小 | workflow 仍依赖 app/model，分层问题未解决 |
| B: app 层预查询并注入 workflow | 分层清晰，单次 run 只查一次 PostgreSQL | 需要调整运行时类型和入口测试 |
**决策**: 选择方案 B
**理由**: 既满足“每次运行查询一次 PostgreSQL”的需求，又满足“workflow 不依赖 app”的分层要求。
**影响**: 影响 app 运行入口、workflow runtime 类型定义、store factory 和相关测试。

---

## 6. 成果设计

N/A（非视觉任务）
