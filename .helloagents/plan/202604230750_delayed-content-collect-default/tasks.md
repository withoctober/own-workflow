# 任务清单: delayed-content-collect-default

```yaml
@feature: delayed-content-collect-default
@created: 2026-04-23
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 4 | 0 | 0 | 4 |

---

## 任务列表

### 1. 方案与脚本落地

- [√] 1.1 新增 `scripts/run_flow_once.py`，支持通过本地 `.env` + PostgreSQL 租户配置直接触发指定租户工作流 | depends_on: []
- [√] 1.2 验证脚本可正确构造 `content-collect/default` 的运行请求，不依赖 HTTP 服务 | depends_on: [1.1]

### 2. 一次性任务投递与记录

- [√] 2.1 为 `default` 租户创建 5 分钟后的单次延迟任务，并将输出写入 `var/logs/delayed-content-collect-default.log` | depends_on: [1.2]
- [√] 2.2 同步更新知识库模块文档与 CHANGELOG，记录一次性延迟执行方案 | depends_on: [2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-23 07:50:00 | 1.1 | completed | 已完成方案包创建并确认采用系统 `at` + 直接触发脚本 |
| 2026-04-23 07:54:00 | 1.2 | completed | 已验证可构造 `content-collect/default` 的运行请求 |
| 2026-04-23 07:55:00 | 2.1 | completed | 已投递单次延迟任务到系统队列 |
| 2026-04-23 07:55:00 | 2.2 | completed | 已同步 KB 文档和 CHANGELOG |

---

## 执行备注

> 本次需求为一次性延迟执行，不适合直接落在现有 `tenant_flow_schedules` 循环 cron 模型中，因此采用系统级一次性队列完成。
