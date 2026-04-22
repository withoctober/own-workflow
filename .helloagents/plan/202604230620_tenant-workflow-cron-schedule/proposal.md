# 变更提案: tenant-workflow-cron-schedule

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-23
```

---

## 1. 需求

### 背景
当前服务已支持多租户、工作流列表和手动触发工作流执行，但缺少租户级的定时触发能力。业务如果需要日报、定时采集或定时生成内容，只能依赖人工调用或外部系统拼装请求，既不稳定，也无法在服务内统一管理运行状态。

用户希望直接在服务内部为某个租户的某条工作流配置 cronjob，并且要求每个租户在每个工作流维度下最多只能有 1 条定时任务，避免重复配置和重复触发。

### 目标
- 新增租户工作流定时任务的数据模型、接口和运行时调度能力。
- 支持按 `tenant_id + flow_id` 唯一配置 1 条 cron 定时任务。
- 支持启停状态、最近执行时间、最近执行结果、最近错误信息、下次执行时间的查询和回写。
- 在服务启动后自动恢复数据库中的激活任务，并在到期时复用现有 `GraphRuntime.run(...)` 触发工作流执行。

### 约束条件
```yaml
时间约束: 本次迭代聚焦服务内定时调度，不扩展额外管理后台
性能约束: 不引入重型任务队列；调度循环需保持轻量，避免显著影响 API 线程
兼容性约束: 保持现有手动触发接口和运行时目录结构不变
业务约束: 每个租户的每个工作流只能存在 1 条 schedule；停用任务后不得继续触发
```

### 验收标准
- [ ] 提供租户工作流 schedule 的创建、查询、更新和删除接口，响应继续遵循统一 `code/message/data` 格式
- [ ] 数据库层确保 `(tenant_id, flow_id)` 唯一约束，重复配置返回明确业务错误
- [ ] 有效 cron 表达式可被校验并计算 `next_run_at`，非法表达式被拒绝
- [ ] 应用启动后能恢复激活中的 schedule，并在到期时自动触发对应工作流执行
- [ ] 每次调度执行后正确回写 `last_run_at`、`last_status`、`last_error`、`next_run_at`
- [ ] 补充测试覆盖接口约束、唯一性校验、调度器关键行为和状态回写逻辑

---

## 2. 方案

### 技术方案
采用“数据库驱动 + 应用内轮询调度器”的实现方式：

- 在 PostgreSQL 中新增 `tenant_flow_schedules` 表，按租户和工作流保存 cron 表达式、启停状态与执行元数据。
- 在 `app.model` 中新增 schedule 的建表、查询、upsert、删除、状态回写接口，并用数据库唯一约束保证 `tenant_id + flow_id` 唯一。
- 在 `app.schemas` 和 `app.routes` 中新增 schedule 相关请求/响应模型与 REST API。
- 在 `workflow.runtime` 下新增轻量调度器，服务启动时拉起后台线程周期扫描到期任务，并在触发时复用 `GraphRuntime.run(...)`。
- 调度器每次执行前后都通过数据库状态更新避免重复执行，并在成功或失败后回写执行结果与下一次触发时间。

### 影响范围
```yaml
涉及模块:
  - app/model.py: 新增 schedule 表结构、CRUD 和状态回写
  - app/schemas.py: 新增 schedule 请求与响应模型
  - app/routes.py: 新增 schedule 管理接口
  - app/main.py: 接入应用生命周期，启动与关闭调度器
  - workflow/runtime/: 新增 schedule 调度器与触发逻辑
  - tests/: 增加路由和调度器测试
  - pyproject.toml: 新增 cron 解析依赖
预计变更文件: 9
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 多实例部署下同一任务被重复触发 | 中 | 本次先在单实例内通过数据库中的运行中标记和条件更新降低重复触发风险，并在实现中保留后续扩展空间 |
| 服务重启后任务恢复不完整 | 中 | 调度器启动时强制从数据库全量加载激活任务并重算 `next_run_at` |
| 调度线程异常退出导致任务静默停止 | 中 | 在线程循环中捕获异常并保留错误日志，关闭时显式停止线程 |
| 新依赖引入不稳定 | 低 | 仅引入 cron 解析库，保持调度主逻辑仍由项目代码掌控 |

---

## 3. 技术设计（可选）

> 涉及架构变更、API设计、数据模型变更时填写

### 架构设计
```mermaid
flowchart TD
    A[FastAPI lifespan] --> B[TenantFlowScheduler]
    B --> C[tenant_flow_schedules]
    B --> D[GraphRuntime.run]
    D --> E[var/runs/{tenant_id}/{flow_id}/{batch_id}]
    D --> F[state.json / events.jsonl]
    B --> C
```

### API设计
#### GET /tenants/{tenant_id}/schedules
- **请求**: 路径参数 `tenant_id`
- **响应**: 当前租户下所有工作流 schedule 列表，包含 cron、状态、最近与下次执行信息

#### PUT /tenants/{tenant_id}/schedules/{flow_id}
- **请求**:
  - `cron`: cron 表达式
  - `is_active`: 是否启用
  - `batch_id_prefix`: 可选，生成运行批次号前缀
- **响应**: 单条 schedule 详情

#### DELETE /tenants/{tenant_id}/schedules/{flow_id}
- **请求**: 路径参数 `tenant_id`、`flow_id`
- **响应**: 删除结果

#### POST /tenants/{tenant_id}/schedules/{flow_id}/trigger
- **请求**: 路径参数 `tenant_id`、`flow_id`
- **响应**: 手动触发结果，用于测试调度链路和复用统一执行逻辑

### 数据模型
| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| tenant_id | text | 业务租户标识 |
| flow_id | text | 工作流标识 |
| cron_expr | text | cron 表达式 |
| is_active | boolean | 是否启用 |
| batch_id_prefix | text | 可选批次号前缀 |
| next_run_at | timestamptz | 下次触发时间 |
| last_run_at | timestamptz | 最近触发时间 |
| last_status | text | 最近一次执行状态，如 `completed` / `failed` |
| last_error | text | 最近一次错误信息 |
| last_batch_id | text | 最近一次触发使用的 batch_id |
| is_running | boolean | 当前是否处于调度执行中 |
| locked_at | timestamptz | 本次执行锁定时间 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: 创建或更新租户工作流定时任务
**模块**: `app.routes` / `app.model`
**条件**: 租户存在，`flow_id` 是系统支持的工作流，传入合法 cron 表达式
**行为**: 写入或更新数据库中的 schedule 记录，并重算 `next_run_at`
**结果**: 同一租户同一工作流始终只有 1 条 schedule，接口返回最新配置

### 场景: 调度器自动触发工作流执行
**模块**: `workflow.runtime.scheduler`
**条件**: schedule 处于启用状态且 `next_run_at` 已到期
**行为**: 调度器锁定该任务，构造 `RunRequest` 并调用 `GraphRuntime.run(...)`
**结果**: 工作流实际执行，运行结果回写到 schedule 元数据

### 场景: 工作流执行失败后的状态回写
**模块**: `workflow.runtime.scheduler`
**条件**: 调度触发的 `GraphRuntime.run(...)` 抛出异常或返回失败状态
**行为**: 更新 `last_status`、`last_error`、`last_run_at` 和新的 `next_run_at`
**结果**: 失败不会阻塞后续调度，且错误可通过接口查询定位

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### tenant-workflow-cron-schedule#D001: 采用数据库驱动的应用内调度器
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 本次需求要求在当前服务内部直接提供 cronjob 能力，并与租户、工作流和运行时状态保持一致。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 数据库驱动的应用内调度器 | 与现有架构一致，状态统一保存在业务表中，容易复用现有 runtime | 未来多实例时需要更强的分布式锁机制 |
| B: APScheduler 驱动 | cron 能力成熟，集成速度快 | 任务状态会分散在 APScheduler 与业务表之间，多实例问题仍需另行处理 |
**决策**: 选择方案 A
**理由**: 当前项目已经以 PostgreSQL 和应用内 runtime 为主，不存在现成的任务系统。数据库驱动方案最容易与租户配置、统一接口和运行状态回写保持一致，改动面也更可控。
**影响**: 影响 `app`、`workflow.runtime`、数据库表结构和测试用例

### tenant-workflow-cron-schedule#D002: 用后台线程轮询替代外部调度依赖
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 需要让服务启动后自动恢复并执行定时任务，同时不希望引入重量级调度基础设施。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 后台线程轮询数据库 | 实现简单、控制清晰、便于单测 | 对多实例和高并发场景扩展性一般 |
| B: 外部 Cron/K8s CronJob | 部署层能力强 | 不符合“服务内完整 cronjob”诉求，且增加运维依赖 |
**决策**: 选择方案 A
**理由**: 当前需求优先解决单服务内的可用性与管理闭环，后台线程轮询足以满足。
**影响**: 需要在 `app.main` 引入 lifespan 生命周期，并新增调度器停止逻辑

---

## 6. 成果设计

> 含视觉产出的任务由 DESIGN Phase2 填充。非视觉任务整节标注"N/A"。

N/A
