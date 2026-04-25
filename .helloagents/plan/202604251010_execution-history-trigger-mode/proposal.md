# 变更提案: execution-history-trigger-mode

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-25
```

---

## 1. 需求

### 背景
当前执行历史已经能记录 `workflow_runs` 的基础状态、节点进度和错误信息，但无法区分一次运行是用户手动发起、按 schedule 手动触发，还是后台 cron 到点自动触发。前端或调用方在查看历史时无法判断来源，也无法对手动运行与定时运行做后续筛选或展示。

### 目标
为执行历史增加明确的触发方式字段，至少支持：
- `manual`: 通过 `POST /api/flows/{flow_id}/runs` 手动发起，或对已有 schedule 执行一次手动触发
- `cron`: 由 `TenantFlowScheduler` 在 cron 到点后自动发起

并且该字段要贯通：
- 运行时 `state.json`
- PostgreSQL `workflow_runs` 元数据表
- `/api/runs` 列表接口
- `/api/flows/{flow_id}/runs/{batch_id}` 详情接口
- 相关文档和测试

### 约束条件
```yaml
时间约束: 本次只补 manual/cron 两种触发方式
性能约束: 不引入额外查询，不改变现有列表分页与运行主链路
兼容性约束: 老数据缺失字段时需要安全回退到空字符串
业务约束: resume 沿用原始 run 的 trigger_mode，不额外创建新的触发方式枚举
```

### 验收标准
- [ ] 手动运行创建的 run 在 `state.json`、`workflow_runs` 和 API 返回中都带有 `trigger_mode=manual`
- [ ] scheduler 自动到点执行的 run 在 `state.json`、`workflow_runs` 和 API 返回中都带有 `trigger_mode=cron`
- [ ] 恢复执行沿用原 run 的 `trigger_mode`
- [ ] 列表和详情接口文档、模型测试、runtime 持久化测试同步更新

---

## 2. 方案

### 技术方案
在运行请求对象 `RunRequest` 和运行上下文 `RuntimeContext` 中引入 `trigger_mode`，并由三条入口注入：
- `/api/flows/{flow_id}/runs` 和 `/api/schedules/{flow_id}/trigger` 写入 `manual`
- `TenantFlowScheduler._execute_schedule()` 写入 `cron`
- `resume` 默认沿用已有 `state.json` 中的 `trigger_mode`

随后由 `StateRepository` 将该字段写入 `state.json` 和 `workflow_runs`，并扩展 `WorkflowRun`、响应 schema、路由构造函数及测试断言。数据库层通过新增 `trigger_mode` 列和兼容迁移保障旧库可平滑升级。

### 影响范围
```yaml
涉及模块:
  - runtime: RunRequest/RuntimeContext/StateRepository 注入并持久化 trigger_mode
  - model: workflow_runs 数据结构、DDL 和 CRUD 扩展 trigger_mode
  - app: 运行列表与详情接口返回 trigger_mode
  - docs: README/api.md/知识库同步说明新增字段说明
预计变更文件: 14
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 旧库缺少 `trigger_mode` 列导致写入失败 | 中 | 在 `ensure_postgres_tables()` 中补列迁移 |
| resume 覆盖触发方式导致历史失真 | 中 | `build_context()` 在 `resume` 且未显式传入时，从已有 `state.json` 回填 |
| 详情接口只读 `state.json`，若未同步字段会出现列表/详情不一致 | 中 | `RuntimeContext.base_state()` 与 `StateRepository.save()` 一起确保字段落盘 |

---

## 3. 技术设计（可选）

### 架构设计
```mermaid
flowchart TD
    A[Manual Run API] --> D[RunRequest(trigger_mode=manual)]
    B[Schedule Trigger API] --> D
    C[Scheduler Auto Run] --> E[RunRequest(trigger_mode=cron)]
    D --> F[GraphRuntime / RuntimeContext]
    E --> F
    F --> G[StateRepository]
    G --> H[state.json]
    G --> I[workflow_runs.trigger_mode]
    I --> J[/api/runs]
    H --> K[/api/flows/{flow_id}/runs/{batch_id}]
```

### API设计
#### GET /api/runs
- **响应新增字段**: `trigger_mode: string`

#### GET /api/flows/{flow_id}/runs/{batch_id}
- **响应新增字段**: `trigger_mode: string`

### 数据模型
| 字段 | 类型 | 说明 |
|------|------|------|
| trigger_mode | text | 执行触发方式，当前支持 `manual` / `cron` |

---

## 4. 核心场景

### 场景: 手动执行历史可区分来源
**模块**: app/runtime/model
**条件**: 用户通过运行接口或 schedule 手动触发接口发起执行
**行为**: 系统创建 run，并在运行元数据和状态详情中记录 `trigger_mode=manual`
**结果**: 执行历史列表和详情都能识别本次运行来自手动触发

### 场景: cron 执行历史可区分来源
**模块**: runtime/model
**条件**: scheduler 按 `next_run_at` 到点执行租户工作流
**行为**: 系统创建 run，并在运行元数据和状态详情中记录 `trigger_mode=cron`
**结果**: 执行历史列表和详情都能识别本次运行来自自动调度

---

## 5. 技术决策

### execution-history-trigger-mode#D001: 触发方式作为 run 元数据持久化字段统一收敛
**日期**: 2026-04-25
**状态**: ✅采纳
**背景**: 需要在执行历史中展示并长期保留“手动/cron”来源，不能只靠批次前缀推断。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 仅通过 `batch_id` 前缀推断 | 无需改表，改动小 | 语义不稳定，manual schedule trigger 无法准确区分，详情接口无法直接返回 |
| B: 新增 `trigger_mode` 到运行上下文与元数据 | 语义明确，列表和详情统一，可扩展更多触发方式 | 需要改数据库、模型和测试 |
**决策**: 选择方案 B
**理由**: 触发方式属于运行历史的核心元数据，应该显式存储，而不是依赖命名约定反推。
**影响**: 影响 `workflow_runs`、运行状态持久化、路由响应模型和文档

---

## 6. 成果设计

N/A
