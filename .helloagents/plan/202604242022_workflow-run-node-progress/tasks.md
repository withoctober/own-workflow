# 任务清单: workflow-run-node-progress

```yaml
@feature: workflow-run-node-progress
@created: 2026-04-24
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 3 | 0 | 0 | 3 |

---

## 任务列表

### 1. 节点进度数据建模

- [√] 1.1 扩展 flow registry、runtime context 和 persistence，统一计算并写入 `total_node_count` 与 `current_node_index` | depends_on: []
- [√] 1.2 扩展 workflow_runs 数据模型、详情接口与列表接口，返回新增节点进度字段 | depends_on: [1.1]

### 2. 验证与同步

- [√] 2.1 同步测试与方案记录，验证所有运行相关接口的返回结构 | depends_on: [1.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-24 20:22 | 方案设计 | completed | 已确认为运行列表、详情、启动、恢复接口统一补充节点进度字段 |
| 2026-04-24 20:28 | 1.1 | completed | 已补充 flow graph 节点元数据访问、state 字段与持久化同步 |
| 2026-04-24 20:31 | 1.2 | completed | 已扩展 workflow_runs、运行列表、运行详情、启动和恢复接口返回字段 |
| 2026-04-24 20:33 | 2.1 | completed | 已同步路由与持久化测试；本地仍受 fastapi/langgraph 等依赖缺失影响，未完成完整自动化执行 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

- 本次沿用现有 flow graph 节点声明顺序作为 `current_node_index` 计算基准。
- 旧 run 详情即使状态文件未写入新增字段，也会在读取时按 flow graph 自动回填节点总数与当前序号。
