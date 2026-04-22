# 任务清单: langgraph-flow-centric-refactor

```yaml
@feature: langgraph-flow-centric-refactor
@created: 2026-04-21
@status: completed
@mode: R3
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 10 | 0 | 0 | 10 |

---

## 任务列表

### 1. 结构重排

- [√] 1.1 新建 `flows/`、`llm/`、`core/`、`integrations/` 目录并定义包结构 | depends_on: []
- [√] 1.2 将原 `graphs/`、`nodes/`、流程专用 `services/*` 迁移到对应 `flows/*` 目录 | depends_on: [1.1]

### 2. 基础能力抽离

- [√] 2.1 将通用 LLM 调用、消息构建、prompt 渲染拆分到 `llm/` | depends_on: [1.1]
- [√] 2.2 将环境变量和文本工具拆分到 `core/`，将热点集成拆分到 `integrations/` | depends_on: [1.1]

### 3. 存储层拆分

- [√] 3.1 将 `stores/factory.py` 拆分为 `base.py`、`local.py`、`feishu.py`、`factory.py` | depends_on: [1.1]
- [√] 3.2 保持 `build_store()`、`StoreError`、辅助函数对 runtime/node 兼容 | depends_on: [3.1]

### 4. 运行时接线

- [√] 4.1 更新 `runtime/` 与 `app/` 导入，切换到 `flows.registry` 和新基础层 | depends_on: [1.2, 2.1, 2.2, 3.2]
- [√] 4.2 更新 `pyproject.toml` 与 `README.md`，反映新的包发现和目录结构 | depends_on: [4.1]

### 5. 清理与验证

- [√] 5.1 删除旧的 `graphs/`、`nodes/`、`services/` 平铺代码目录 | depends_on: [4.1]
- [√] 5.2 新增运行时或图装配 smoke test，并完成基础验证 | depends_on: [5.1, 4.2]

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-21 18:34 | 方案包创建 | completed | 已创建 implementation 类型方案包 |
| 2026-04-21 18:40 | 方案选择 | completed | 已确认采用 Flow-Centric 重构方案 |
| 2026-04-21 19:02 | 结构迁移 | completed | flow/core/llm/integrations/stores 新结构已落地 |
| 2026-04-21 19:06 | 兼容接线 | completed | runtime/app/pyproject/README 已切换到新结构 |
| 2026-04-21 19:08 | 验证完成 | completed | `.venv/bin/python -m unittest discover -s tests` 通过 |

---

## 执行备注

> 本次重构目标是“一次性切到新结构”，不保留旧目录兼容包装。
> 验证使用仓库内 `.venv` 解释器；系统自带 `python3` 未安装 LangGraph 依赖，不作为本次验证基准。
