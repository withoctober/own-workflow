# 模块: delivery

## 职责

- 提供项目级容器镜像构建入口。
- 定义 GitHub Actions 的镜像构建与推送流程。
- 约束镜像默认启动命令与服务入口保持一致。

## 行为规范

- 项目根目录 `Dockerfile` 负责构建当前 `uv + FastAPI` 服务镜像。
- 镜像默认使用 `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` 启动应用。
- GitHub Actions workflow 位于 `.github/workflows/build-and-push-image.yml`。
- workflow 在任意分支 `push` 时触发，先登录腾讯云镜像仓库，再构建并推送镜像。
- workflow 当前只负责镜像构建与推送，不负责部署和通知。
- 镜像 tag 采用 `${github.ref_name}`，便于按分支区分发布产物。

## 依赖关系

- 依赖 `Dockerfile` 使用 `pyproject.toml` 和 `uv.lock` 安装运行依赖。
- 依赖 `app.main` 作为服务启动入口。
- 依赖 GitHub Secrets `QCLOUD_REGISTRY_USERNAME` 和 `QCLOUD_REGISTRY_PASSWORD` 完成镜像仓库认证。
