# 变更提案: run-resume-retry

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
当前工作流运行时会把单次执行的 `state.json`、节点状态和 checkpoint 持久化到 `var/runs/...` 目录，但当某个 run 在中途失败或进入 `blocked` 后，系统只能重新发起一次新的 run，不能对已有失败 run 做“从失败节点开始”的显式恢复。

这导致两个问题：

- 已完成节点会被重复执行，增加外部接口调用和重复写入风险。
- 对外部使用者来说，失败后缺少统一的重试入口，只能手工拼接新的运行请求。

### 目标
- 为已有失败 run 增加显式 `resume` 能力。
- 恢复时保留已完成节点结果，仅重试失败或阻塞节点及其后续节点。
- 提供独立 HTTP 入口，便于外部系统对指定 run 发起恢复。
- 补充测试，验证恢复路径不会重复执行已完成节点。

### 约束条件
```yaml
兼容性约束: 现有 POST /flows/{flow_id}/runs 语义保持不变
实现约束: 不依赖 LangGraph 隐式 checkpoint 恢复成功与否，恢复逻辑由 runtime 显式控制
状态约束: 仅允许对 failed / blocked 的 run 执行 resume
数据约束: 恢复沿用原 batch_id 和运行目录，不创建新的 run 目录
```

### 验收标准
- [ ] 新增独立 `resume` HTTP 接口，可针对指定 `flow_id + tenant_id + batch_id` 发起恢复
- [ ] runtime 能识别 resume 请求，并跳过 `completed_nodes` 中的节点
- [ ] resume 前会清理失败节点的错误态，确保失败节点能够重新执行
- [ ] 对 `failed` / `blocked` 之外的 run 发起 resume 会返回明确错误
- [ ] 单测覆盖 runtime 与 API 路径，验证恢复时已完成节点不重复执行

---

## 2. 方案

### 技术方案
采用“显式恢复模式 + 节点包装跳过”的实现方式：

- 在 `RunRequest` 中增加 `resume` 标识，由 `GraphRuntime.resume(...)` 构造恢复请求。
- 在 runtime 进入执行前读取现有 `state.json`，验证当前 run 状态是否允许恢复，并记录恢复来源节点。
- 对每个 graph node 的包装函数增加恢复判断：若当前为 resume 且节点已在 `completed_nodes` 中，则直接跳过，不重复执行节点逻辑。
- 恢复前清理失败节点和 run 级错误态，避免旧错误阻塞本次执行；恢复完成后继续沿用现有状态持久化与事件记录机制。
- 在 `app.routes` 中新增 `POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume` 入口，复用租户运行时配置获取逻辑。

### 影响范围
```yaml
涉及模块:
  - workflow/runtime/engine.py: 新增 resume 入口与节点跳过逻辑
  - workflow/runtime/persistence.py: 新增恢复前状态校验与清理能力
  - app/routes.py: 新增 resume API
  - app/schemas.py: 按需新增恢复响应说明（复用现有请求模型）
  - tests/: 新增 runtime 与 route 恢复测试
  - README.md: 更新 API 与运行说明
  - .helloagents/modules/runtime.md: 同步 runtime 恢复行为
  - .helloagents/modules/app.md: 同步 API 新入口
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| 恢复时重复执行已完成节点 | 中 | 由 runtime 包装层显式跳过 `completed_nodes` |
| 旧错误态残留导致恢复后状态异常 | 中 | 在 resume 前集中清理失败节点状态和 run 级 `errors/current_node` |
| 外部接口误对已完成 run 发起恢复 | 低 | 在 repository 层校验 run 状态，仅允许 `failed/blocked` |

---

## 3. 技术设计

### API 设计
#### POST /flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume
- **请求**: 路径参数 `flow_id`、`tenant_id`、`batch_id`
- **响应**: 恢复后的 run 结果，继续使用统一 `code/message/data` 格式

### 数据与状态设计
新增或增强以下状态字段：

| 字段 | 说明 |
|------|------|
| `resume_count` | 当前 run 已恢复次数 |
| `resumed_from_node` | 本次恢复时识别出的失败/阻塞节点 |
| `last_resumed_at` | 最近一次恢复时间 |

### 恢复流程
1. 读取现有 `state.json`
2. 校验 `status in {failed, blocked}`
3. 识别失败或阻塞节点，清理其旧状态与 run 级错误
4. 重新编译 graph，并以原 `batch_id` 执行
5. 对已完成节点直接跳过，对失败节点重新执行

---

## 4. 核心场景

### 场景: 对失败 run 发起恢复
**模块**: `app.routes` / `workflow.runtime.engine`
**条件**: 指定 run 已存在且状态为 `failed` 或 `blocked`
**行为**: runtime 清理失败态，跳过已完成节点，从失败节点重新执行
**结果**: run 使用原目录继续推进，成功时状态更新为 `completed`

### 场景: 对非失败 run 发起恢复
**模块**: `workflow.runtime.persistence`
**条件**: run 状态不是 `failed` 或 `blocked`
**行为**: 拒绝恢复并返回明确错误
**结果**: 防止对 `completed/running/pending` run 做无意义或危险重试

---

## 5. 技术决策

### run-resume-retry#D001: 使用显式跳过已完成节点，而非依赖 LangGraph 自动 checkpoint 恢复
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 现有同一 `thread_id` 下重复执行并不会自然从失败节点恢复，仍会从入口节点重新执行。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 显式跳过 completed 节点 | 逻辑可控，行为清晰，可单测验证 | graph 仍会从入口遍历一次 |
| B: 完全依赖 LangGraph checkpoint 恢复 | 理论上更“原生” | 当前行为不满足需求，且恢复时机不透明 |
**决策**: 选择方案 A
**理由**: 当前项目最需要稳定可预期的恢复语义，而不是依赖底层框架的隐式行为。
**影响**: 影响 runtime 节点包装逻辑与状态仓储接口设计

