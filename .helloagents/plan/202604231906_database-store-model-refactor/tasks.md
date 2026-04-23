# 任务清单: database-store-model-refactor

```yaml
@feature: database-store-model-refactor
@created: 2026-04-23
@status: completed
@mode: R3
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 6 | 0 | 0 | 6 |

---

## 任务列表

### 1. 共享 model 层拆分

- [√] 1.1 新建顶层 `model/` 目录并迁移 `app/model.py` 的类型、建表和 CRUD 能力 | depends_on: []
- [√] 1.2 更新 `app`、`workflow.runtime`、脚本和测试的导入路径到新的 `model` 层 | depends_on: [1.1]

### 2. 数据库存储接入

- [√] 2.1 在 `model/store_entry.py` 中实现 `store_entries` 表及基础 CRUD | depends_on: [1.1]
- [√] 2.2 在 `workflow/store/database.py` 中实现 `DatabaseStore` 和内置 dataset registry | depends_on: [2.1]
- [√] 2.3 更新 `workflow/store/factory.py`，支持数据库与飞书 store 的选择逻辑 | depends_on: [2.2]

### 3. 测试与回归

- [√] 3.1 更新并补充单元测试，覆盖 model 导入链路、store factory 与 DatabaseStore 基本行为 | depends_on: [1.2, 2.3]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-23 19:06 | 方案包创建 | completed | 已创建 implementation 方案包 |
| 2026-04-23 19:20 | 共享 model 层迁移 | completed | 删除 `app/model.py`，新增顶层 `model/` 包并完成导入切换 |
| 2026-04-23 19:24 | 数据库存储接入 | completed | 新增 `store_entries` CRUD、`DatabaseStore` 与工厂切换逻辑 |
| 2026-04-23 19:27 | 回归测试 | completed | 使用 `.venv/bin/python -m unittest` 通过 33 个相关测试 |
| 2026-04-23 19:35 | Feishu store 清理 | completed | 删除运行时 `FeishuStore` 与对应测试，工厂固定返回 `DatabaseStore` |
| 2026-04-23 20:05 | 飞书配置接口与运行配置链路清理 | completed | 删除 `/tenant/feishu` 与 `/tenants/{tenant_id}/feishu` 接口，运行配置统一改为 `get_tenant_runtime_config`，并通过 28 个相关测试 |
| 2026-04-23 20:18 | 飞书实现残留清理 | completed | 删除 `workflow/integrations/feishu.py`、清理 README/Prompt/元数据中的飞书依赖表述，并再次通过 28 个相关测试 |
| 2026-04-23 20:36 | 表格 CRUD API 接入 | completed | 新增 `/tenant/tables` 与 `/tenants/{tenant_id}/tables` 系列表格接口，支持列表、查询、新增、编辑、删除，并通过 34 个相关测试 |
| 2026-04-23 20:42 | 表格 API 路径收敛 | completed | 按要求将简化路径从 `/tenant/tables` 调整为 `/tables`，显式租户路径保持不变，并再次通过 34 个相关测试 |
| 2026-04-23 20:47 | 显式租户表格路径移除 | completed | 删除 `/tenants/{tenant_id}/tables` 系列表格接口，仅保留 `/tables` 路径，并再次通过 34 个相关测试 |
| 2026-04-23 20:55 | API 前缀统一 | completed | 所有 HTTP 接口统一增加 `/api` 前缀，测试与文档同步更新，并再次通过 34 个相关测试 |
| 2026-04-23 21:02 | 调度路径收敛 | completed | 将简化调度路径从 `/api/tenant/schedules` 调整为 `/api/schedules`，测试与 `api.md` 同步更新，并再次通过 34 个相关测试 |
| 2026-04-23 21:10 | 显式租户调度路径移除 | completed | 删除 `/api/tenants/{tenant_id}/schedules` 系列接口，仅保留 `/api/schedules` 路径，测试与文档同步更新，并通过 33 个相关测试 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等
- 用户明确要求：直接执行，完成后开始测试；无阻塞问题不再反复询问。
- 本次按一次性迁移方案执行，不保留 `app/model.py` 兼容壳。
