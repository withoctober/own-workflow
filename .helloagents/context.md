# 项目上下文

## 技术栈

- Python 3.11+
- FastAPI
- LangChain
- LangGraph
- Uvicorn

## 当前结构约定

- Flow 相关代码必须优先放在 `flows/<flow_name>/`
- 通用 LLM 与 prompt 能力放在 `llm/`
- 第三方接口能力放在 `integrations/`
- 基础工具放在 `core/`
- Store 相关实现放在 `stores/`

## 当前流程

- `content-collect`
- `daily-report`
- `content-create-original`
- `content-create-rewrite`
