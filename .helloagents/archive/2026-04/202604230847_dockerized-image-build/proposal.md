# 变更提案: dockerized-image-build

## 元信息
```yaml
类型: 新功能
方案类型: implementation
优先级: P1
状态: 已确认
创建: 2026-04-23
```

---

## 1. 需求

### 背景
当前项目已经是可运行的 `uv + FastAPI + Uvicorn` 服务，但仓库内还没有统一的容器构建入口和 GitHub Actions 发布流程。用户希望补齐容器化能力，并参考现有示例接入镜像构建与推送，但本次明确只做“构建并推送镜像”，不包含 Dokploy 部署和 Feishu 通知。

### 目标
- 为当前仓库新增可直接用于生产镜像构建的项目根目录 `Dockerfile`
- 新增 GitHub Actions workflow，在任意分支 push 时构建并推送镜像
- 工作流使用当前项目真实结构，不再引用不存在的 `apps/web/Dockerfile`

### 约束条件
```yaml
时间约束: 无
性能约束: 镜像构建应尽量复用 uv 锁文件，避免运行时重新解析依赖
兼容性约束: 保持当前 Python 3.11+ / uv 依赖体系；启动方式需兼容现有环境变量与 .env 读取逻辑
业务约束: 本次不接入 Dokploy 部署、不发送 Feishu 通知，不改动现有业务代码行为
```

### 验收标准
- [ ] 根目录存在可用于当前 FastAPI 服务的 `Dockerfile`，容器默认启动 `app.main:app`
- [ ] `.github/workflows/` 下存在构建推送 workflow，引用根目录 `Dockerfile`
- [ ] workflow 使用腾讯云镜像仓库登录凭据和镜像 tag 规则，不包含部署与通知步骤

---

## 2. 方案

### 技术方案
基于 `python:3.11-slim` 构建运行镜像，安装 `uv` 后使用 `uv sync --frozen --no-dev` 将应用依赖安装到系统环境，再复制业务代码并通过 `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` 启动服务。

GitHub Actions 侧新增单一 workflow，监听所有分支的 `push`，执行仓库检出、登录腾讯云镜像仓库、基于根目录上下文构建并推送镜像。镜像 tag 沿用用户提供的 `${{ github.ref_name }}` 规则。

### 影响范围
```yaml
涉及模块:
  - runtime: 运行服务新增容器化入口与镜像启动约定
  - ci-cd: 新增 GitHub Actions 镜像构建与推送流程
  - knowledge-base: 同步记录容器化交付方式
预计变更文件: 7
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| `uv sync --frozen` 在 CI/镜像环境与本地锁文件不兼容 | 中 | 直接基于仓库内 `uv.lock` 安装，保持与本地一致 |
| 容器默认端口或启动命令与现有服务入口不一致 | 中 | 明确使用 `app.main:app` 和 `0.0.0.0:8000` |
| workflow 沿用错误的 Node/Web 路径 | 低 | 改为引用根目录 `Dockerfile` 和当前 Python 项目结构 |

---

## 3. 技术设计（可选）

> 本次不涉及 API 与数据模型变更。

---

## 4. 核心场景

### 场景: 构建并推送镜像
**模块**: runtime / ci-cd
**条件**: 仓库发生 `push`，且 GitHub Secrets 中已配置镜像仓库用户名和密码
**行为**: GitHub Actions 使用根目录 `Dockerfile` 构建镜像并推送到 `uswccr.ccs.tencentyun.com/inpolar/own-workflow:${{ github.ref_name }}`
**结果**: 当前分支对应镜像成功产出，可供后续外部部署系统消费

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### dockerized-image-build#D001: 容器镜像直接基于当前 uv 项目结构构建
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 用户给出的参考 workflow 指向 `apps/web/Dockerfile`，但当前仓库是根目录 Python 服务，没有前端子应用结构，必须重新确定构建入口。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 根目录 `Dockerfile` + uv 安装依赖 | 与当前仓库结构一致，部署入口清晰，维护成本低 | 需要显式安装 uv |
| B: 沿用示例中的 `apps/web/Dockerfile` 路径 | 接近用户示例 | 与当前仓库结构不匹配，无法直接使用 |
**决策**: 选择方案 A
**理由**: 当前项目就是单一 Python 服务，直接在根目录定义镜像入口最稳定，也能避免引入不存在的子目录假设。
**影响**: 影响容器化构建约定、GitHub Actions workflow 路径和后续部署系统接入方式

---

## 6. 成果设计

> 含视觉产出的任务由 DESIGN Phase2 填充。非视觉任务整节标注"N/A"。

N/A
