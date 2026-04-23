# 项目上下文

## 技术栈

- Python 3.11+
- FastAPI
- LangChain
- LangGraph
- Uvicorn
- uv
- Docker
- GitHub Actions

## 当前结构约定

- Flow 相关代码放在 `workflow/flow/<flow_name>/`
- 通用模型与 prompt 能力放在 `workflow/core/`
- 第三方接口能力放在 `workflow/integrations/`
- 运行时能力放在 `workflow/runtime/`
- 应用入口与 HTTP 路由放在 `app/`
- 容器化入口位于仓库根目录 `Dockerfile`
- GitHub Actions 工作流位于 `.github/workflows/`

## 当前流程

- `content-collect`
- `daily-report`
- `content-create-original`
- `content-create-rewrite`
