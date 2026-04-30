# 任务清单: fix-uni-image-prompt-field

> **@status:** completed | 2026-04-28 22:27

```yaml
@feature: fix-uni-image-prompt-field
@created: 2026-04-28
@status: completed
@mode: R2
```

## 进度概览

| 完成 | 失败 | 跳过 | 总数 |
|------|------|------|------|
| 3 | 0 | 0 | 3 |

---

## 任务列表

### 1. 图片提示词校验

- [√] 1.1 在 `workflow/flow/content_create/generation.py` 中校验配图 `cover_prompt` 非空 | depends_on: []
  - 备注: 已统一处理 Pydantic 对象和 dict 输出。
- [√] 1.2 在 `workflow/integrations/image_generation.py` 中拦截全空 prompt 列表，避免远端请求 | depends_on: [1.1]
  - 备注: `uni` payload 字段保持小写 `prompt`。

### 2. 验证

- [√] 2.1 运行图片生成和提示词解析相关测试，确认回归通过 | depends_on: [1.2]
  - 备注: `uv run python -m unittest tests.test_content_create_images tests.test_generation_aliases` 通过。

---

## 执行日志

| 时间 | 任务 | 状态 | 备注 |
|------|------|------|------|
| 2026-04-28 22:22 | 方案设计 | 完成 | 初步定位到 Uni 文生图参数错误 |
| 2026-04-28 22:30 | 根因修正 | 完成 | 根据 Uni curl 示例更正判断：小写 prompt 正确，修复空提示词校验 |
| 2026-04-28 22:31 | 测试验证 | 完成 | 相关 23 个测试通过 |
| 2026-04-28 22:33 | 索引防护 | 完成 | 空内页提示词直接报错，避免过滤后图片槽位错位 |

---

## 执行备注

> 记录执行过程中的重要说明、决策变更、风险提示等

- 本次不修改 `uni` 文生图字段名，仍沿用官方兼容 OpenAI 的小写 `prompt`。
- 原始错误 `field Prompt is required` 由远端返回，结合 curl 示例判断更可能是空 prompt 被远端视为缺失。
