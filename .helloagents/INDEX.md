# own-workflow Knowledge Base

```yaml
kb_version: 3
project: own-workflow
updated: 2026-04-24
```

## 概览

- 当前项目已完成一次 flow-centric 重构。
- 运行时入口仍为 FastAPI + GraphRuntime。
- 流程定义已从旧的平铺结构迁移到 `workflow/flow/` 聚合结构。
- 当前仓库已补齐根目录 `Dockerfile` 与 GitHub Actions 镜像构建推送流程。
- `/api/flows` 现会为每个工作流返回 `run_request_schema`，用于声明可执行参数及其必填状态。

## 关键目录

- `app/`: HTTP 接口入口
- `workflow/runtime/`: GraphRuntime、状态持久化、运行上下文与调度器
- `workflow/flow/`: 按流程组织的 graph / nodes / generation / prompts
- `workflow/core/`: LangChain/LangGraph 共享模型调用、环境变量与 prompt 能力
- `workflow/integrations/`: 第三方接口
- `workflow/store/`: store 协议、飞书后端与工厂装配
- `.github/workflows/`: CI/CD 工作流
