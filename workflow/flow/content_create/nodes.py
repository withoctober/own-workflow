from __future__ import annotations

from typing import Any

from workflow.flow.common import block_state, persist_step_output, skip_if_blocked, write_artifact
from workflow.runtime.context import RuntimeContext
from workflow.core.ai import build_message_trace
from workflow.flow.content_create.utils import (
    build_rewrite_prompt_targets,
    build_work_record,
    extract_source_post_image_urls,
    fetch_source_post_from_tikhub,
    filter_work_record,
    generate_images,
    latest_by_date,
)
from workflow.flow.content_create.generation import (
    generate_original_copy,
    generate_original_image_prompts,
    generate_rewrite_copy,
    generate_rewrite_image_prompts,
)
from workflow.store import StoreError


def original_copy(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        daily_report = latest_by_date(data_store.read_table("日报"))
        if not marketing_plan.strip() or not daily_report:
            return block_state(runtime, state, "缺少营销策划方案或日报输入")

        try:
            result = generate_original_copy(runtime.root, {"marketing_plan": marketing_plan, "daily_report": daily_report})
            payload = result.value
        except ValueError as exc:
            return block_state(runtime, state, f"原创文案输出无效: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id="create-original-01-copy",
            output=payload,
            artifacts=[
                write_artifact(runtime, "create-original-01-copy", "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, "create-original-01-copy", "draft_copy.json", payload),
            ],
            message="已生成原创文案",
        )

    return node


def original_images(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        draft_copy = dict(state.get("outputs", {}).get("create-original-01-copy", {}))
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        daily_report = latest_by_date(data_store.read_table("日报"))
        if not marketing_plan.strip() or not daily_report or not draft_copy:
            return block_state(runtime, state, "缺少营销策划方案、日报或原创文案输入")

        try:
            result = generate_original_image_prompts(
                runtime.root,
                {"marketing_plan": marketing_plan, "daily_report": daily_report, "draft_copy": draft_copy},
            )
            prompt_payload = result.value
            image_payload = generate_images(
                {
                    "root": str(runtime.root),
                    "step": {"image_model": "doubao-seedream-5-0-260128", "image_size": "1728x2304"},
                    "batch_id": runtime.batch_id,
                },
                [prompt_payload["cover_prompt"], *prompt_payload.get("image_prompts", [])],
            )
            record = build_work_record(
                {"batch_id": runtime.batch_id},
                draft_copy,
                prompt_payload,
                image_payload,
            )
            filtered = filter_work_record(data_store.list_table_fields("生成作品库"), record)
            data_store.write_table("生成作品库", [filtered], mode="append_latest")
        except (ValueError, StoreError) as exc:
            return block_state(runtime, state, f"原创配图或写入失败: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id="create-original-02-images",
            output={"record": filtered},
            artifacts=[
                write_artifact(runtime, "create-original-02-images", "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, "create-original-02-images", "image_prompts.json", prompt_payload),
                write_artifact(runtime, "create-original-02-images", "image_results.json", image_payload),
            ],
            message="已生成原创配图并写入作品库",
        )

    return node


def rewrite_fetch(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        try:
            payload = fetch_source_post_from_tikhub(
                runtime.root,
                runtime.source_url,
                endpoint="https://api.tikhub.io/api/v1/xiaohongshu/web/get_note_info_v4",
                api_key_env="TIKHUB_API_KEY",
                timeout=60,
            )
        except StoreError as exc:
            return block_state(runtime, state, str(exc))
        source_post = payload["source_post"]
        return persist_step_output(
            runtime,
            state,
            step_id="create-rewrite-01-fetch",
            output=source_post,
            artifacts=[
                write_artifact(runtime, "create-rewrite-01-fetch", "tikhub_request.json", payload["request"]),
                write_artifact(runtime, "create-rewrite-01-fetch", "tikhub_response.json", payload["response"]),
                write_artifact(runtime, "create-rewrite-01-fetch", "source_post.json", source_post),
            ],
            message="已通过 Tikhub 抓取对标笔记",
        )

    return node


def rewrite_copy(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        source_post = dict(state.get("outputs", {}).get("create-rewrite-01-fetch", {}))
        marketing_plan = runtime.store().read_doc("营销策划方案")
        if not marketing_plan.strip() or not source_post:
            return block_state(runtime, state, "缺少营销策划方案或 Tikhub 抓取内容")

        try:
            result = generate_rewrite_copy(runtime.root, {"marketing_plan": marketing_plan, "source_post": source_post})
            payload = result.value
        except ValueError as exc:
            return block_state(runtime, state, f"二创文案输出无效: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id="create-rewrite-02-copy",
            output=payload,
            artifacts=[
                write_artifact(runtime, "create-rewrite-02-copy", "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, "create-rewrite-02-copy", "draft_copy.json", payload),
            ],
            message="已生成二创文案",
        )

    return node


def rewrite_images(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        source_post = dict(state.get("outputs", {}).get("create-rewrite-01-fetch", {}))
        draft_copy = dict(state.get("outputs", {}).get("create-rewrite-02-copy", {}))
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        if not marketing_plan.strip() or not source_post or not draft_copy:
            return block_state(runtime, state, "缺少营销策划方案、抓取内容或二创文案输入")

        reference_targets = build_rewrite_prompt_targets(extract_source_post_image_urls(source_post))
        if not reference_targets:
            return block_state(runtime, state, "未从抓取结果中提取到可用参考图")

        prompts: dict[str, Any] = {"cover_prompt": "", "image_prompts": []}
        artifacts: list[str] = []
        for target in reference_targets:
            try:
                result = generate_rewrite_image_prompts(
                    runtime.root,
                    {"marketing_plan": marketing_plan, "source_post": source_post, "draft_copy": draft_copy},
                    extra_text=(
                        f"# 当前参考图片\n\n当前这次只允许参考这一张图，为【{target['role_name']}】单独生成 1 条二创配图提示词。"
                        "不要综合其他参考图，不要输出多张结果，不要做整组风格平均。"
                        "最终请只返回合法 JSON，并把当前这一条提示词写入 `cover_prompt`，`image_prompts` 返回空数组。"
                    ),
                    extra_images=[str(target["image_url"])],
                )
                payload = result.value
            except ValueError as exc:
                return block_state(runtime, state, f"二创配图提示词输出无效: {exc}")
            current_prompt = str(payload.get("cover_prompt", "")).strip() or next(
                (str(item).strip() for item in payload.get("image_prompts", []) if str(item).strip()),
                "",
            )
            if not current_prompt:
                return block_state(runtime, state, f"二创配图提示词输出缺少 {target['role_name']} 提示词")
            if target["target_key"] == "cover_prompt":
                prompts["cover_prompt"] = current_prompt
            else:
                prompts["image_prompts"].append(current_prompt)
            artifacts.append(
                write_artifact(
                    runtime,
                    "create-rewrite-03-images",
                    f"{target['artifact_suffix']}.prompt.md",
                    build_message_trace(result.messages),
                )
            )

        try:
            image_payload = generate_images(
                {
                    "root": str(runtime.root),
                    "step": {"image_model": "doubao-seedream-5-0-260128", "image_size": "1728x2304"},
                    "batch_id": runtime.batch_id,
                },
                [prompts["cover_prompt"], *prompts.get("image_prompts", [])],
            )
            record = build_work_record({"batch_id": runtime.batch_id}, draft_copy, prompts, image_payload)
            filtered = filter_work_record(data_store.list_table_fields("生成作品库"), record)
            data_store.write_table("生成作品库", [filtered], mode="append_latest")
        except (ValueError, StoreError) as exc:
            return block_state(runtime, state, f"二创配图或写入失败: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id="create-rewrite-03-images",
            output={"record": filtered},
            artifacts=artifacts + [
                write_artifact(runtime, "create-rewrite-03-images", "image_prompts.json", prompts),
                write_artifact(runtime, "create-rewrite-03-images", "image_results.json", image_payload),
            ],
            message="已生成二创配图并写入作品库",
        )

    return node
