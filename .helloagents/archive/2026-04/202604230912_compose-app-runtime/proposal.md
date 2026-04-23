# 变更提案: compose-app-runtime

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
当前仓库已经具备 `Dockerfile`，但本地运行仍需要手工拼装 `docker run` 参数。用户希望补一个 `docker-compose` 文件，让服务可以直接启动，同时本次明确只复用现有 `.env` 与外部 PostgreSQL，不在 Compose 内再拉数据库容器。

### 目标
- 新增可直接运行当前应用容器的 Compose 配置
- 让 Compose 复用现有 `.env` 中的 `DATABASE_URL` 等环境变量
- 补充文档，让本地可直接通过 `docker compose up` 拉取既有镜像并启动服务

### 约束条件
```yaml
时间约束: {如有}
性能约束: 无额外性能目标，保持现有镜像启动方式
兼容性约束: Compose 只启动应用服务，直接使用已发布镜像并继续暴露 8000 端口
业务约束: 不新增本地 PostgreSQL 容器，不修改现有外部数据库接入方式
```

### 验收标准
- [ ] 根目录新增 `docker-compose.yml`，可直接启动当前应用服务
- [ ] Compose 配置复用仓库 `.env`，并暴露 `8000` 端口
- [ ] README 补充 `docker compose up` 使用方式

---

## 2. 方案

### 技术方案
新增根目录 `docker-compose.yml`，定义单个 `app` 服务，直接使用已发布镜像 `uswccr.ccs.tencentyun.com/inpolar/own-workflow:main`，并通过 `env_file: .env` 注入环境变量。容器端口映射为 `8000:8000`，重启策略设置为 `unless-stopped`，运行目录挂载保留 `./var:/app/var` 以便持久化运行产物。

### 影响范围
```yaml
涉及模块:
  - delivery: 新增 Compose 运行入口并统一本地容器启动方式
  - documentation: 补充 Compose 使用文档
  - knowledge-base: 记录 Compose 运行约定
预计变更文件: 7
```

### 风险评估
| 风险 | 等级 | 应对 |
|------|------|------|
| `.env` 中外部数据库不可达导致容器启动后接口不可用 | 中 | 在文档中明确 Compose 只负责起应用容器，数据库依赖仍由外部提供 |
| Compose 指向的镜像 tag 未及时更新 | 中 | 当前固定使用 `main` 镜像，后续如需切分环境可改为变量化 tag |

---

## 3. 技术设计（可选）

> 涉及架构变更、API设计、数据模型变更时填写

> 本次不涉及 API 与数据模型变更。

---

## 4. 核心场景

> 执行完成后同步到对应模块文档

### 场景: 本地一键启动应用容器
**模块**: delivery
**条件**: 本地已安装 Docker / Docker Compose，仓库根目录存在 `.env`
**行为**: 执行 `docker compose up`
**结果**: Compose 拉取已发布镜像并启动应用容器，监听本地 `8000` 端口，运行时继续使用 `.env` 中配置的外部 PostgreSQL

---

## 5. 技术决策

> 本方案涉及的技术决策，归档后成为决策的唯一完整记录

### compose-app-runtime#D001: Compose 仅封装应用服务并复用现有外部 PostgreSQL
**日期**: 2026-04-23
**状态**: ✅采纳
**背景**: 用户明确选择 Compose 只起应用服务，不在本地增加 PostgreSQL 容器。
**选项分析**:
| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 仅应用服务 + 复用 `.env` 中外部数据库 + 直接拉已发布镜像 | 启动最简单，不依赖本地构建，符合用户要求 | 本地启动仍依赖外部数据库连通性和远端镜像可用性 |
| B: 基于本地 Dockerfile 构建应用服务 | 可本地即时验证未发布变更 | 与用户最新要求不符，仍依赖本地构建 |
**决策**: 选择方案 A
**理由**: 这次目标只是降低应用容器启动门槛，并且用户明确要求不要基于 Dockerfile，而是直接基于之前已发布的镜像。
**影响**: 影响本地容器运行方式、README 使用说明和知识库 delivery 模块说明

---

## 6. 成果设计

> 含视觉产出的任务由 DESIGN Phase2 填充。非视觉任务整节标注"N/A"。

N/A
