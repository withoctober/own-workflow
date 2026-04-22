# own-workflow Knowledge Base

```yaml
kb_version: 3
project: own-workflow
updated: 2026-04-21
```

## 概览

- 当前项目已完成一次 flow-centric 重构。
- 运行时入口仍为 FastAPI + GraphRuntime。
- 流程定义已从旧的 `graphs/`、`nodes/`、`services/` 平铺结构迁移到 `flows/` 聚合结构。

## 关键目录

- `app/`: HTTP 接口入口
- `runtime/`: GraphRuntime、状态持久化、运行上下文
- `flows/`: 按流程组织的 graph / nodes / generation / prompts
- `llm/`: LangChain/LangGraph 共享模型调用与 prompt 能力
- `integrations/`: 第三方接口
- `stores/`: store 协议、本地后端、飞书后端、工厂装配
