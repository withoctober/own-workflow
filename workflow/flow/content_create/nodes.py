from __future__ import annotations

from typing import Any

from workflow.flow.common import (
    block_state,
    fail_timed_step,
    finish_timed_step,
    log_node_step,
    log_timed_step,
    persist_step_output,
    skip_if_blocked,
    write_artifact,
    write_failure_snapshot,
    write_stage_snapshot,
)
from workflow.runtime.context import RuntimeContext
from workflow.core.ai import build_message_trace
from workflow.flow.content_create.utils import (
    build_artifact_payload,
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
from model import upsert_artifact


def _write_content_artifact(
    runtime: RuntimeContext,
    *,
    copy_payload: dict[str, Any],
    prompt_payload: dict[str, Any],
    image_payload: dict[str, Any],
    step_id: str,
) -> dict[str, Any]:
    tenant_config = runtime.tenant_runtime_config
    database_url = tenant_config.database_url if tenant_config is not None else ""
    if not database_url:
        raise StoreError("缺少 database_url，无法写入 artifact 业务表")
    payload = build_artifact_payload(
        {
            "tenant_id": runtime.tenant_id,
            "flow_id": runtime.flow_id,
            "batch_id": runtime.batch_id,
            "workflow_run_id": runtime.batch_id,
            "source_url": runtime.source_url,
            "artifact_type": "content",
        },
        copy_payload,
        prompt_payload,
        image_payload,
    )
    artifact = upsert_artifact(database_url, **payload)
    return {
        "artifact_id": artifact.id,
        "title": artifact.title,
        "artifact_type": artifact.artifact_type,
        "batch_id": artifact.batch_id,
    }


def original_copy(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "create-original-01-copy"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        daily_report = latest_by_date(data_store.read_table("日报"))
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取原创文案生成输入",
            detail={"has_marketing_plan": bool(marketing_plan.strip()), "has_daily_report": bool(daily_report)},
        )
        if not marketing_plan.strip() or not daily_report:
            return block_state(runtime, state, "缺少营销策划方案或日报输入")

        try:
            generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成原创文案")
            result = generate_original_copy(
                runtime.root,
                {"marketing_plan": marketing_plan, "daily_report": daily_report},
                tenant_config=runtime.tenant_runtime_config,
            )
            payload = result.value
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="generation",
                started_at=generation_started,
                message="原创文案生成完成",
                detail={"keys": list(payload.keys())},
            )
        except ValueError as exc:
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="generation",
                error=str(exc),
                detail={"stage": "original_copy"},
            )
            fail_timed_step(
                runtime,
                step_id=step_id,
                phase="generation",
                started_at=generation_started,
                message="原创文案生成失败",
                detail={"error": str(exc)},
                level="warning",
            )
            return block_state(runtime, state, f"原创文案输出无效: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output=payload,
            artifacts=[
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, step_id, "draft_copy.json", payload),
            ],
            message="已生成原创文案",
        )

    return node


def original_images(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "create-original-02-images"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        draft_copy = dict(state.get("outputs", {}).get("create-original-01-copy", {}))
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        daily_report = latest_by_date(data_store.read_table("日报"))
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取原创配图生成输入",
            detail={
                "has_marketing_plan": bool(marketing_plan.strip()),
                "has_daily_report": bool(daily_report),
                "has_draft_copy": bool(draft_copy),
            },
        )
        if not marketing_plan.strip() or not daily_report or not draft_copy:
            return block_state(runtime, state, "缺少营销策划方案、日报或原创文案输入")

        try:
            prompt_started = log_timed_step(runtime, step_id=step_id, phase="prompt_generation", message="开始生成原创配图提示词")
            result = generate_original_image_prompts(
                runtime.root,
                {"marketing_plan": marketing_plan, "daily_report": daily_report, "draft_copy": draft_copy},
                tenant_config=runtime.tenant_runtime_config,
            )
            prompt_payload = result.value
            prompt_snapshot = write_stage_snapshot(
                runtime,
                step_id=step_id,
                phase="prompt_generation",
                detail={"image_prompt_count": len(prompt_payload.get("image_prompts", [])) + 1},
                payload=prompt_payload,
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="prompt_generation",
                started_at=prompt_started,
                message="原创配图提示词生成完成",
                detail={"image_prompt_count": len(prompt_payload.get("image_prompts", [])) + 1},
            )
            image_started = log_timed_step(runtime, step_id=step_id, phase="image_generation", message="开始生成原创配图")
            image_payload = generate_images(
                {
                    "root": str(runtime.root),
                    "step": {"image_model": "doubao-seedream-5-0-260128", "image_size": "1728x2304"},
                    "batch_id": runtime.batch_id,
                    "tenant_config": runtime.tenant_runtime_config,
                },
                [prompt_payload["cover_prompt"], *prompt_payload.get("image_prompts", [])],
            )
            image_snapshot = write_stage_snapshot(
                runtime,
                step_id=step_id,
                phase="image_generation",
                detail={"prompt_count": len([prompt_payload["cover_prompt"], *prompt_payload.get("image_prompts", [])])},
                payload=image_payload,
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="image_generation",
                started_at=image_started,
                message="原创配图生成完成",
                detail={"result_count": len(image_payload.get("images", [])) if isinstance(image_payload, dict) else None},
            )
            record = build_work_record(
                {"batch_id": runtime.batch_id},
                draft_copy,
                prompt_payload,
                image_payload,
            )
            filtered = filter_work_record(data_store.list_table_fields("生成作品库"), record)
            write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入生成作品库")
            data_store.write_table("生成作品库", [filtered], mode="append_latest")
            artifact_summary = _write_content_artifact(
                runtime,
                copy_payload=draft_copy,
                prompt_payload=prompt_payload,
                image_payload=image_payload,
                step_id=step_id,
            )
            store_snapshot = write_stage_snapshot(
                runtime,
                step_id=step_id,
                phase="store_write",
                detail={"row_count": 1, "artifact_id": artifact_summary["artifact_id"]},
                payload={"record": filtered, "artifact": artifact_summary},
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="store_write",
                started_at=write_started,
                message="已写入生成作品库和 artifact 表",
                detail={"row_count": 1, "artifact_id": artifact_summary["artifact_id"]},
            )
        except (ValueError, StoreError) as exc:
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="generation",
                error=str(exc),
                detail={"stage": "original_images"},
                payload={
                    "draft_copy": draft_copy,
                    "has_marketing_plan": bool(marketing_plan.strip()),
                    "has_daily_report": bool(daily_report),
                },
            )
            log_node_step(
                runtime,
                step_id=step_id,
                event="generation_error",
                message="原创配图或写入失败",
                detail={"error": str(exc)},
                level="warning",
            )
            return block_state(runtime, state, f"原创配图或写入失败: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"record": filtered, "artifact": artifact_summary},
            artifacts=[
                *prompt_snapshot,
                *image_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, step_id, "image_prompts.json", prompt_payload),
                write_artifact(runtime, step_id, "image_results.json", image_payload),
            ],
            message="已生成原创配图并写入作品库和 artifact 表",
        )

    return node


def rewrite_fetch(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "create-rewrite-01-fetch"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        try:
            fetch_started = log_timed_step(
                runtime,
                step_id=step_id,
                phase="source_fetch",
                message="开始通过 Tikhub 抓取对标笔记",
                detail={"source_url": runtime.source_url},
            )
            payload = fetch_source_post_from_tikhub(
                runtime.root,
                runtime.source_url,
                endpoint="https://api.tikhub.io/api/v1/xiaohongshu/web/get_note_info_v4",
                api_key_env="TIKHUB_API_KEY",
                timeout=60,
                tenant_config=runtime.tenant_runtime_config,
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="source_fetch",
                started_at=fetch_started,
                message="对标笔记抓取完成",
                detail={"has_source_post": bool(payload.get("source_post"))},
            )
        except StoreError as exc:
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="source_fetch",
                error=str(exc),
                detail={"source_url": runtime.source_url},
            )
            fail_timed_step(
                runtime,
                step_id=step_id,
                phase="source_fetch",
                started_at=fetch_started,
                message="对标笔记抓取失败",
                detail={"error": str(exc)},
                level="warning",
            )
            return block_state(runtime, state, str(exc))
        source_post = payload["source_post"]
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output=source_post,
            artifacts=[
                write_artifact(runtime, step_id, "tikhub_request.json", payload["request"]),
                write_artifact(runtime, step_id, "tikhub_response.json", payload["response"]),
                write_artifact(runtime, step_id, "source_post.json", source_post),
            ],
            message="已通过 Tikhub 抓取对标笔记",
        )

    return node


def rewrite_copy(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "create-rewrite-02-copy"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        source_post = dict(state.get("outputs", {}).get("create-rewrite-01-fetch", {}))
        marketing_plan = runtime.store().read_doc("营销策划方案")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取二创文案生成输入",
            detail={"has_marketing_plan": bool(marketing_plan.strip()), "has_source_post": bool(source_post)},
        )
        if not marketing_plan.strip() or not source_post:
            return block_state(runtime, state, "缺少营销策划方案或 Tikhub 抓取内容")

        try:
            generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成二创文案")
            result = generate_rewrite_copy(
                runtime.root,
                {"marketing_plan": marketing_plan, "source_post": source_post},
                tenant_config=runtime.tenant_runtime_config,
            )
            payload = result.value
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="generation",
                started_at=generation_started,
                message="二创文案生成完成",
                detail={"keys": list(payload.keys())},
            )
        except ValueError as exc:
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="generation",
                error=str(exc),
                detail={"stage": "rewrite_copy"},
                payload={"source_post": source_post},
            )
            fail_timed_step(
                runtime,
                step_id=step_id,
                phase="generation",
                started_at=generation_started,
                message="二创文案生成失败",
                detail={"error": str(exc)},
                level="warning",
            )
            return block_state(runtime, state, f"二创文案输出无效: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output=payload,
            artifacts=[
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, step_id, "draft_copy.json", payload),
            ],
            message="已生成二创文案",
        )

    return node


def rewrite_images(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "create-rewrite-03-images"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        source_post = dict(state.get("outputs", {}).get("create-rewrite-01-fetch", {}))
        draft_copy = dict(state.get("outputs", {}).get("create-rewrite-02-copy", {}))
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取二创配图生成输入",
            detail={
                "has_marketing_plan": bool(marketing_plan.strip()),
                "has_source_post": bool(source_post),
                "has_draft_copy": bool(draft_copy),
            },
        )
        if not marketing_plan.strip() or not source_post or not draft_copy:
            return block_state(runtime, state, "缺少营销策划方案、抓取内容或二创文案输入")

        reference_targets = build_rewrite_prompt_targets(extract_source_post_image_urls(source_post))
        log_node_step(
            runtime,
            step_id=step_id,
            event="reference_targets_resolved",
            message="已解析参考图目标",
            detail={"target_count": len(reference_targets)},
        )
        if not reference_targets:
            return block_state(runtime, state, "未从抓取结果中提取到可用参考图")

        prompts: dict[str, Any] = {"cover_prompt": "", "image_prompts": []}
        artifacts: list[str] = []
        for target in reference_targets:
            try:
                prompt_started = log_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="prompt_generation",
                    message=f"开始生成 {target['role_name']} 的二创配图提示词",
                    detail={"image_url": str(target["image_url"])},
                )
                result = generate_rewrite_image_prompts(
                    runtime.root,
                    {"marketing_plan": marketing_plan, "source_post": source_post, "draft_copy": draft_copy},
                    extra_text=(
                        f"# 当前参考图片\n\n当前这次只允许参考这一张图，为【{target['role_name']}】单独生成 1 条二创配图提示词。"
                        "不要综合其他参考图，不要输出多张结果，不要做整组风格平均。"
                        "最终请只返回合法 JSON，并把当前这一条提示词写入 `cover_prompt`，`image_prompts` 返回空数组。"
                    ),
                    extra_images=[str(target["image_url"])],
                    tenant_config=runtime.tenant_runtime_config,
                )
                payload = result.value
                prompt_snapshot = write_stage_snapshot(
                    runtime,
                    step_id=step_id,
                    phase=f"{target['artifact_suffix']}.prompt_generation",
                    detail={"role_name": target["role_name"], "has_cover_prompt": bool(str(payload.get('cover_prompt', '')).strip())},
                    payload=payload,
                )
                finish_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="prompt_generation",
                    started_at=prompt_started,
                    message=f"{target['role_name']} 的二创配图提示词生成完成",
                    detail={"has_cover_prompt": bool(str(payload.get('cover_prompt', '')).strip())},
                )
            except ValueError as exc:
                write_failure_snapshot(
                    runtime,
                    step_id=step_id,
                    phase=f"{target['artifact_suffix']}.prompt_generation",
                    error=str(exc),
                    detail={"role_name": target["role_name"], "image_url": str(target["image_url"])},
                )
                fail_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="prompt_generation",
                    started_at=prompt_started,
                    message=f"{target['role_name']} 的二创配图提示词生成失败",
                    detail={"error": str(exc)},
                    level="warning",
                )
                return block_state(runtime, state, f"二创配图提示词输出无效: {exc}")
            current_prompt = str(payload.get("cover_prompt", "")).strip() or next(
                (str(item).strip() for item in payload.get("image_prompts", []) if str(item).strip()),
                "",
            )
            if not current_prompt:
                write_failure_snapshot(
                    runtime,
                    step_id=step_id,
                    phase=f"{target['artifact_suffix']}.prompt_generation",
                    error=f"二创配图提示词输出缺少 {target['role_name']} 提示词",
                    detail={"target_key": target["target_key"], "role_name": target["role_name"]},
                    payload=payload,
                )
                log_node_step(
                    runtime,
                    step_id=step_id,
                    event="prompt_missing",
                    message=f"{target['role_name']} 的二创配图提示词缺失",
                    detail={"target_key": target["target_key"]},
                    level="warning",
                )
                return block_state(runtime, state, f"二创配图提示词输出缺少 {target['role_name']} 提示词")
            if target["target_key"] == "cover_prompt":
                prompts["cover_prompt"] = current_prompt
            else:
                prompts["image_prompts"].append(current_prompt)
            artifacts.extend(prompt_snapshot)
            artifacts.append(
                write_artifact(
                    runtime,
                    step_id,
                    f"{target['artifact_suffix']}.prompt.md",
                    build_message_trace(result.messages),
                )
            )

        try:
            image_started = log_timed_step(runtime, step_id=step_id, phase="image_generation", message="开始生成二创配图")
            image_payload = generate_images(
                {
                    "root": str(runtime.root),
                    "step": {"image_model": "doubao-seedream-5-0-260128", "image_size": "1728x2304"},
                    "batch_id": runtime.batch_id,
                    "tenant_config": runtime.tenant_runtime_config,
                },
                [prompts["cover_prompt"], *prompts.get("image_prompts", [])],
            )
            artifacts.extend(
                write_stage_snapshot(
                    runtime,
                    step_id=step_id,
                    phase="image_generation",
                    detail={"prompt_count": len([prompts["cover_prompt"], *prompts.get("image_prompts", [])])},
                    payload=image_payload,
                )
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="image_generation",
                started_at=image_started,
                message="二创配图生成完成",
                detail={"prompt_count": len([prompts["cover_prompt"], *prompts.get("image_prompts", [])])},
            )
            record = build_work_record({"batch_id": runtime.batch_id}, draft_copy, prompts, image_payload)
            filtered = filter_work_record(data_store.list_table_fields("生成作品库"), record)
            write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入生成作品库")
            data_store.write_table("生成作品库", [filtered], mode="append_latest")
            artifact_summary = _write_content_artifact(
                runtime,
                copy_payload=draft_copy,
                prompt_payload=prompts,
                image_payload=image_payload,
                step_id=step_id,
            )
            artifacts.extend(
                write_stage_snapshot(
                    runtime,
                    step_id=step_id,
                    phase="store_write",
                    detail={"row_count": 1, "artifact_id": artifact_summary["artifact_id"]},
                    payload={"record": filtered, "artifact": artifact_summary},
                )
            )
            finish_timed_step(
                runtime,
                step_id=step_id,
                phase="store_write",
                started_at=write_started,
                message="已写入生成作品库和 artifact 表",
                detail={"row_count": 1, "artifact_id": artifact_summary["artifact_id"]},
            )
        except (ValueError, StoreError) as exc:
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="generation",
                error=str(exc),
                detail={"stage": "rewrite_images"},
                payload={"prompts": prompts, "draft_copy": draft_copy},
            )
            log_node_step(
                runtime,
                step_id=step_id,
                event="generation_error",
                message="二创配图或写入失败",
                detail={"error": str(exc)},
                level="warning",
            )
            return block_state(runtime, state, f"二创配图或写入失败: {exc}")
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"record": filtered, "artifact": artifact_summary},
            artifacts=artifacts + [
                write_artifact(runtime, step_id, "image_prompts.json", prompts),
                write_artifact(runtime, step_id, "image_results.json", image_payload),
            ],
            message="已生成二创配图并写入作品库和 artifact 表",
        )

    return node
