# 任务清单: tenant-name-only-create

```yaml
@feature: tenant-name-only-create
@created: 2026-04-22
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 5 | 0 | 0 | 5 |

---

## 任务列表

### 1. 接口与模型

- [√] 1.1 在 `app/model.py` 中实现 `tenant_id` 自动生成能力 | depends_on: []
- [√] 1.2 在 `app/schemas.py` 中新增仅名称创建租户的请求模型 | depends_on: [1.1]
- [√] 1.3 在 `app/routes.py` 中新增 `POST /tenants` 并复用现有写库逻辑 | depends_on: [1.1, 1.2]

### 2. 验证与文档

- [√] 2.1 在 `tests/test_app_routes.py` 中补充新接口测试 | depends_on: [1.3]
- [√] 2.2 更新 `README.md` 并启动服务执行真实创建验证 | depends_on: [1.3, 2.1]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-22 20:23 | 方案包创建 | completed | 已创建 implementation 方案包 |
| 2026-04-22 20:23 | 方案确认 | completed | 确认新增 POST 接口并保留 PUT 兼容路径 |
| 2026-04-22 20:27 | 接口与模型开发 | completed | 已新增 POST /tenants 与 tenant_id 自动生成逻辑 |
| 2026-04-22 20:28 | 测试验证 | completed | `uv run python -m unittest tests.test_app_model tests.test_app_routes` 通过 |
| 2026-04-22 20:30 | 真实创建验证 | completed | 服务启动后通过 POST /tenants 创建 `演示租户` 成功 |

---

## 执行备注

> 本次变更不调整 PostgreSQL 表结构，仅调整租户创建入口和 `tenant_id` 生成方式。
> 真实验证中发现 `upsert_tenant` SQL 占位符数量错误，已修复并补充单测覆盖。
