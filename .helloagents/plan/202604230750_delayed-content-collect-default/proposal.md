# 变更提案: delayed-content-collect-default

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已完成
创建: 2026-04-23
```

---

## 1. 需求

### 背景
当前项目已经支持租户级 cron schedule，但用户本次需求是为 `default` 租户创建一个“5 分钟后执行一次内容收集流程”的任务。该需求属于一次性延迟触发，不适合直接落成项目内置的循环 cron 配置。

### 目标
为 `default` 租户创建一次性延迟任务，在约 5 分钟后触发 `content-collect` 流程，并保留执行日志，且不依赖当前 HTTP 服务必须处于运行状态。

### 约束条件
```yaml
时间约束: 需要在当前时间基础上约 5 分钟后触发
性能约束: 不引入常驻后台进程，不修改现有调度器核心行为
兼容性约束: 复用现有 GraphRuntime、PostgreSQL 租户配置和项目 .env
业务约束: 目标租户固定为 default，目标流程固定为 content-collect，且只执行一次
```

### 验收标准
- [ ] 存在可直接执行的单次触发脚本，可在项目根目录通过本地环境直接触发指定租户工作流
- [ ] 已创建一次性系统级延迟任务，计划在 2026-04-23 07:53 CST 左右触发 `default/content-collect`
- [ ] 任务执行输出会写入项目日志目录，便于后续追踪结果

---

## 2. 方案

### 技术方案
新增一个轻量脚本，直接读取项目 `.env` 和 PostgreSQL 中的租户飞书运行配置，复用 `GraphRuntime.run(...)` 触发指定租户的指定流程。实际的一次性“5 分钟后执行”使用系统 `at` 队列投递，在触发时调用该脚本并将 stdout/stderr 重定向到日志文件。

### 影响范围
```yaml
涉及模块:
  - runtime: 复用现有运行时入口做手动一次性触发
  - app: 无接口变更，但保留与现有租户/配置数据模型的一致性
预计变更文件: 6
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| `at` 服务未启用导致任务不执行 | 中 | 先检查 `at` 命令可用，再投递队列并记录任务号 |
| 目标租户缺少飞书配置导致运行失败 | 中 | 投递前验证 `default` 租户和飞书配置均存在 |
| 一次性任务执行后难以追踪 | 低 | 输出统一落到 `var/logs/` 下的日志文件 |

---

## 3. 技术设计（可选）

### 架构设计
```mermaid
flowchart TD
    A[at 单次任务] --> B[scripts/run_flow_once.py]
    B --> C[WorkflowSettings.from_root]
    B --> D[get_feishu_runtime_config]
    C --> E[GraphRuntime.run]
    D --> E
    E --> F[var/runs/{tenant_id}/{flow_id}/{batch_id}]
    B --> G[var/logs/delayed-content-collect-default.log]
```

---

## 4. 核心场景

### 场景: 一次性延迟触发默认租户内容收集
**模块**: runtime
**条件**: 本地项目 `.env` 可用，`default` 租户和飞书配置已存在，系统支持 `at`
**行为**: 系统在 5 分钟后执行一次 `scripts/run_flow_once.py --flow-id content-collect --tenant-id default`
**结果**: `content-collect` 流程被触发一次，运行产物写入 `var/runs/`，命令输出写入 `var/logs/`

---

## 5. 技术决策

### delayed-content-collect-default#D001: 一次性任务采用系统 `at` 队列而非内置 cron schedule
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 用户明确要求“5 分钟后执行一次”，而项目内置的 `tenant_flow_schedules` 只表达循环 cron，不适合原生表示单次延迟触发。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 新增数据库层 one-shot schedule 能力 | 与项目调度体系统一 | 需要扩展表结构、调度器语义和测试，超出本次需求 |
| B: 使用系统 `at` + 直接触发脚本 | 改动最小、一次性语义准确、立即可用 | 依赖宿主机 `at` 能力，任务状态不回写数据库 schedule 表 |
**决策**: 选择方案 B
**理由**: 本次目标是尽快创建一次性延迟执行任务，系统级 `at` 更贴合“一次执行后结束”的语义，同时能复用现有运行时而不侵入现有 cron 体系。
**影响**: 新增一次性执行脚本与日志路径，不修改现有 `tenant_flow_schedules` 行为

---

## 6. 成果设计

N/A。本次交付为运行脚本、系统延迟任务和知识库记录，不涉及视觉产出。
