# 任务清单: workflow-runtime-config-injection

```yaml
@feature: workflow-runtime-config-injection
@created: 2026-04-22
@status: in_progress
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 0 | 0 | 0 | 4 |

---

## 任务列表

### 1. 运行时解耦

- [ ] 1.1 在 `workflow/` 中移除对 `app.settings`、`app.utils`、`app.model` 的直接依赖 | depends_on: []
- [ ] 1.2 在 `workflow/runtime` 与 `workflow/store` 中接入注入式 tenant runtime config | depends_on: [1.1]

### 2. 入口注入与验证

- [ ] 2.1 在 `app.routes.run_flow` 中执行 PostgreSQL 预查询并将租户配置注入 `RunRequest` | depends_on: [1.2]
- [ ] 2.2 更新并运行相关测试，验证单次 run 注入行为和运行时兼容性 | depends_on: [2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-22 21:29 | 方案包创建 | completed | 已创建 implementation 方案包 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等
- 用户明确要求：workflow 不依赖 app，租户配置必须在 app 层解析后注入 workflow 上下文。
