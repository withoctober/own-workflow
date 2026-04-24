from __future__ import annotations

import urllib.error
from typing import Any

from workflow.flow.common import (
    block_state,
    fail_timed_step,
    finish_timed_step,
    log_node_step,
    log_timed_step,
    persist_step_output,
    skip_if_blocked,
    soft_fail_state,
    write_artifact,
    write_failure_snapshot,
    write_stage_snapshot,
)
from workflow.runtime.context import RuntimeContext
from workflow.integrations.hotspots import fetch_daily_hotspots_from_step, merge_hotspot_rows
from workflow.core.ai import build_message_trace
from workflow.flow.content_create.utils import fetch_user_notes_from_tikhub, resolve_profile_user_id
from workflow.flow.content_collect.generation import (
    generate_industry_keywords,
    generate_industry_report,
    generate_keyword_matrix,
    generate_marketing_plan,
    generate_topic_bank,
)
from workflow.store import first_text as first_table_value, non_empty_count


CUSTOMER_FIELDS = ["品牌名称", "行业", "门店数量", "品牌成立时间", "品牌介绍", "企业介绍", "小红书品牌账号链接"]
PRODUCT_FIELDS = [
    "产品名称",
    "价格",
    "产品定位",
    "目标人群",
    "解决痛点",
    "使用场景",
    "差异化优势",
    "市场地位",
    "产品详细介绍",
    "主要竞品名称",
    "竞品价格",
    "竞品解决痛点",
    "竞品使用场景",
    "竞品市场地位",
    "竞品详细介绍",
]
TOPIC_FIELDS = [
    "爆款标题",
    "具体场景",
    "用户痛点",
    "解决方案",
    "小红书种草价值点",
    "小红书选题思路",
]

KEYWORD_STORE_FIELD_MAP = {
    "keywords": "关键词",
    "industry_keywords": "行业关键词",
}
TOPIC_STORE_FIELD_MAP = {
    "hit_title": "爆款标题",
    "scenario": "具体场景",
    "pain_point": "用户痛点",
    "solution": "解决方案",
    "xiaohongshu_value": "小红书种草价值点",
    "topic_idea": "小红书选题思路",
}

BENCHMARK_POST_STORE_FIELD_MAP = {
    "note_url": "笔记链接",
    "author_name": "作者名",
    "title": "标题",
    "content": "正文",
    "tags": "标签",
    "like_count": "点赞数",
    "favorite_count": "收藏数",
    "share_count": "分享数",
    "image_urls_text": "配图链接",
    "cover_url": "封面链接",
    "published_at": "发布时间",
    "extracted_at": "提取时间",
    "error_message": "报错信息",
}
BENCHMARK_POST_NUMBER_FIELDS = {"点赞数", "收藏数", "分享数"}
DAILY_HOTSPOT_STEP_CONFIG = {
    "api_config": {
        "api_key_env": "TIKHUB_API_KEY",
    }
}


def _map_fields(payload: dict[str, Any], field_map: dict[str, str]) -> dict[str, str]:
    return {target_key: str(payload.get(source_key, "")).strip() for source_key, target_key in field_map.items()}


def _normalize_store_field_value(field_name: str, value: Any) -> Any:
    if field_name not in BENCHMARK_POST_NUMBER_FIELDS:
        return "" if value is None else str(value).strip()
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _normalize_benchmark_post(note: dict[str, Any], account: dict[str, Any], batch_id: str) -> dict[str, str]:
    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    image_urls: list[str] = []
    for candidate in (
        note.get("images_list"),
        note.get("image_list"),
        note.get("images"),
        [note.get("cover")] if isinstance(note.get("cover"), dict) else [],
    ):
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str) and item.strip():
                    image_urls.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("url", "original", "url_default", "url_pre", "image_url", "url_size_large"):
                        value = str(item.get(key, "")).strip()
                        if value:
                            image_urls.append(value)
                            break
    deduped_urls: list[str] = []
    seen: set[str] = set()
    for url in image_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped_urls.append(url)

    note_id = str(note.get("note_id") or note.get("id") or "").strip()
    note_url = str(note.get("note_url") or note.get("share_url") or "").strip()
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    tags: list[str] = []
    for candidate in (note.get("topics"), note.get("tag_list"), note.get("tags"), note.get("hash_tag")):
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str) and item.strip():
                    tags.append(item.strip())
                elif isinstance(item, dict):
                    value = str(item.get("name") or item.get("tag_name") or "").strip()
                    if value:
                        tags.append(value)
    tag_text = " ".join(f"#{tag.lstrip('#')}" for tag in tags if tag)

    published_raw = note.get("time") or note.get("publish_time") or note.get("last_update_time") or ""
    published_at = str(published_raw).strip()
    if isinstance(published_raw, (int, float)):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        timestamp = float(published_raw)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        published_at = datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "note_url": note_url,
        "author_name": str(user.get("nickname") or user.get("name") or account.get("账号名称") or "").strip(),
        "title": str(note.get("title") or note.get("display_title") or "").strip(),
        "content": str(note.get("desc") or note.get("content") or note.get("description") or "").strip(),
        "tags": tag_text,
        "like_count": str(note.get("liked_count") or note.get("likes") or "").strip(),
        "favorite_count": str(note.get("collected_count") or note.get("collect_count") or "").strip(),
        "share_count": str(note.get("shared_count") or note.get("share_count") or "").strip(),
        "image_urls_text": "\n".join(deduped_urls),
        "cover_url": deduped_urls[0] if deduped_urls else "",
        "published_at": published_at,
        "extracted_at": batch_id,
        "error_message": "",
    }

def coordinator_check(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-01-coordinator-check"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        started_at = log_timed_step(runtime, step_id=step_id, phase="validation", message="开始校验资料完整性")
        data_store = runtime.store()
        customers = data_store.read_table("客户背景资料")
        products = data_store.read_table("产品库")
        benchmark_accounts = data_store.read_table("对标账号库")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取资料校验所需数据",
            detail={
                "customers": len(customers),
                "products": len(products),
                "benchmark_accounts": len(benchmark_accounts),
            },
        )
        customer_ok = max((non_empty_count(record, CUSTOMER_FIELDS) for record in customers), default=0) >= 6
        product_ok = max((non_empty_count(record, PRODUCT_FIELDS) for record in products), default=0) >= 8
        benchmark_ok = any(str(record.get("主页链接", "")).strip() for record in benchmark_accounts)
        if not (customer_ok and product_ok and benchmark_ok):
            missing: list[str] = []
            if not customer_ok:
                missing.append("客户背景资料不足 6 个有效字段")
            if not product_ok:
                missing.append("产品库不足 8 个有效字段")
            if not benchmark_ok:
                missing.append("对标账号库缺少主页链接")
            fail_timed_step(
                runtime,
                step_id=step_id,
                phase="validation",
                started_at=started_at,
                message="资料校验未通过",
                detail={"missing": missing},
                level="warning",
            )
            write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="validation",
                error="；".join(missing),
                detail={"missing": missing},
            )
            return block_state(runtime, state, "；".join(missing))
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="validation",
            started_at=started_at,
            message="资料校验通过",
        )
        return persist_step_output(runtime, state, step_id=step_id, message="资料校验通过")

    return node


def industry_keywords(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-02-industry-keywords"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        customers = data_store.read_table("客户背景资料")
        products = data_store.read_table("产品库")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取行业关键词生成输入",
            detail={"customers": len(customers), "products": len(products)},
        )
        values = {
            "industry": first_table_value(customers, "行业", default="行业"),
            "brand": first_table_value(customers, "品牌名称", default=""),
            "product_name": first_table_value(products, "产品名称", default="产品"),
            "audience": first_table_value(products, "目标人群", default=""),
            "customer_background": customers,
            "products": products,
        }
        generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成行业关键词")
        result = generate_industry_keywords(runtime.root, values, tenant_config=runtime.tenant_runtime_config)
        payload = result.value
        generation_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="generation",
            detail={"keys": list(payload.keys())},
            payload=payload,
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="generation",
            started_at=generation_started,
            message="行业关键词生成完成",
            detail={"keys": list(payload.keys())},
        )
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入关键词及行业关键词")
        data_store.write_table("关键词及行业关键词", [_map_fields(payload, KEYWORD_STORE_FIELD_MAP)], mode="replace")
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"row_count": 1},
            payload=_map_fields(payload, KEYWORD_STORE_FIELD_MAP),
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入关键词及行业关键词",
            detail={"row_count": 1},
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output=payload,
            artifacts=[
                *generation_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, step_id, "response.json", payload),
            ],
            message="已生成关键词及行业关键词",
        )

    return node


def industry_report(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-03-industry-report"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        keyword_records = data_store.read_table("关键词及行业关键词")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取行业报告生成输入",
            detail={"keyword_records": len(keyword_records)},
        )
        if not keyword_records:
            return block_state(runtime, state, "缺少“关键词及行业关键词”输入")
        raw_keywords = "、".join(
            [str(value).strip() for record in keyword_records for value in (record.get("行业关键词"), record.get("关键词")) if str(value).strip()]
        )
        values = {
            "today": runtime.batch_id,
            "keywords_record": keyword_records[0],
            "raw_keywords": raw_keywords or "行业关键词",
        }
        generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成行业报告")
        result = generate_industry_report(runtime.root, values, tenant_config=runtime.tenant_runtime_config)
        report = result.value
        generation_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="generation",
            detail={"content_length": len(report)},
            payload={"content": report},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="generation",
            started_at=generation_started,
            message="行业报告生成完成",
            detail={"content_length": len(report)},
        )
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入行业报告")
        data_store.write_doc("行业报告", report)
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"doc_name": "行业报告"},
            payload={"content": report},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入行业报告",
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"content": report},
            artifacts=[
                *generation_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, step_id, "report.md", report),
            ],
            message="已生成行业报告",
        )

    return node


def benchmark_posts(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-04-benchmark-posts"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        accounts = data_store.read_table("对标账号库")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取对标账号库",
            detail={"accounts": len(accounts)},
        )
        if not accounts:
            return block_state(runtime, state, "缺少“对标账号库”输入")

        raw_payloads: list[dict[str, Any]] = []
        collected_rows: list[dict[str, str]] = []
        errors: list[str] = []
        seen_note_urls: set[str] = set()

        for account in accounts:
            homepage_url = str(account.get("主页链接", "")).strip()
            account_name = str(account.get("账号名称", "")).strip() or homepage_url
            log_node_step(
                runtime,
                step_id=step_id,
                event="account_processing",
                message=f"开始处理对标账号 {account_name}",
                detail={"homepage_url": homepage_url},
            )
            if not homepage_url:
                errors.append(f"{account_name}: 缺少主页链接")
                raw_payloads.append(
                    {
                        "account": account,
                        "profile": {},
                        "pages": [],
                        "status": "skipped",
                        "error": "缺少主页链接",
                    }
                )
                continue

            try:
                profile_started = log_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="profile_resolve",
                    message=f"开始解析账号 {account_name} 的 user_id",
                    detail={"homepage_url": homepage_url},
                )
                profile = resolve_profile_user_id(homepage_url, timeout=30)
                finish_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="profile_resolve",
                    started_at=profile_started,
                    message=f"账号 {account_name} 的 user_id 解析完成",
                    detail={"has_user_id": bool(str(profile.get('user_id', '')).strip())},
                )
            except Exception as exc:
                fail_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="profile_resolve",
                    started_at=profile_started,
                    message=f"账号 {account_name} 的 user_id 解析失败",
                    detail={"error": str(exc)},
                    level="warning",
                )
                write_failure_snapshot(
                    runtime,
                    step_id=step_id,
                    phase="profile_resolve",
                    error=str(exc),
                    detail={"account_name": account_name, "homepage_url": homepage_url},
                )
                errors.append(f"{account_name}: {exc}")
                raw_payloads.append(
                    {
                        "account": account,
                        "profile": {},
                        "pages": [],
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            user_id = str(profile.get("user_id", "")).strip()
            if not user_id:
                errors.append(f"{account_name}: 未能从主页链接解析真实 user_id")
                raw_payloads.append(
                    {
                        "account": account,
                        "profile": profile,
                        "pages": [],
                        "status": "failed",
                        "error": "未能从主页链接解析真实 user_id",
                    }
                )
                continue

            last_cursor = ""
            account_notes: list[dict[str, Any]] = []
            account_payloads: list[dict[str, Any]] = []
            account_errors: list[str] = []
            try:
                fetch_started = log_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="note_fetch",
                    message=f"开始抓取账号 {account_name} 的作品",
                    detail={"user_id": user_id},
                )
                while True:
                    payload = fetch_user_notes_from_tikhub(
                        runtime.root,
                        user_id=user_id,
                        last_cursor=last_cursor,
                        timeout=60,
                        tenant_config=runtime.tenant_runtime_config,
                    )
                    account_payloads.append(payload)
                    account_notes.extend([note for note in payload.get("notes", []) if isinstance(note, dict)])
                    log_node_step(
                        runtime,
                        step_id=step_id,
                        event="page_fetched",
                        message=f"已抓取账号 {account_name} 的一页作品",
                        detail={
                            "page_count": len(account_payloads),
                            "notes_in_page": len(payload.get("notes", [])),
                            "has_more": bool(payload.get("has_more")),
                        },
                    )
                    has_more = bool(payload.get("has_more"))
                    next_cursor = str(payload.get("last_cursor", "")).strip()
                    if not has_more or not next_cursor or next_cursor == last_cursor:
                        break
                    last_cursor = next_cursor
                finish_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="note_fetch",
                    started_at=fetch_started,
                    message=f"账号 {account_name} 的作品抓取完成",
                    detail={"page_count": len(account_payloads), "note_count": len(account_notes)},
                )
            except Exception as exc:
                fail_timed_step(
                    runtime,
                    step_id=step_id,
                    phase="note_fetch",
                    started_at=fetch_started,
                    message=f"账号 {account_name} 的作品抓取失败",
                    detail={"error": str(exc), "page_count": len(account_payloads)},
                    level="warning",
                )
                write_failure_snapshot(
                    runtime,
                    step_id=step_id,
                    phase="note_fetch",
                    error=str(exc),
                    detail={"account_name": account_name, "user_id": user_id, "page_count": len(account_payloads)},
                    payload={"pages": account_payloads},
                )
                errors.append(f"{account_name}: {exc}")
                raw_payloads.append(
                    {
                        "account": account,
                        "profile": profile,
                        "pages": account_payloads,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            raw_payloads.append(
                {
                    "account": account,
                    "profile": profile,
                    "pages": account_payloads,
                    "status": "completed",
                    "error": "",
                }
            )
            if not account_notes:
                account_errors.append("未抓取到作品")
                errors.append(f"{account_name}: {'；'.join(account_errors)}")
                continue

            for note in account_notes:
                if isinstance(note, dict):
                    row = _normalize_benchmark_post(note, account, runtime.batch_id)
                    note_url = str(row.get("note_url", "")).strip()
                    if note_url and note_url in seen_note_urls:
                        continue
                    if row["note_url"] or row["title"] or row["content"]:
                        if note_url:
                            seen_note_urls.add(note_url)
                        collected_rows.append(row)

        if not collected_rows:
            artifacts = [
                *write_failure_snapshot(
                    runtime,
                    step_id=step_id,
                    phase="note_fetch",
                    error="对标作品抓取失败，未生成可写入记录",
                    detail={"error_count": len(errors)},
                    payload={"errors": errors, "payload_count": len(raw_payloads)},
                ),
                write_artifact(runtime, step_id, "tikhub_payloads.json", raw_payloads),
                write_artifact(runtime, step_id, "errors.json", errors),
            ]
            return soft_fail_state(
                runtime,
                state,
                step_id=step_id,
                message="对标作品抓取失败，未生成可写入记录，已按非阻塞失败继续流程",
                output={"rows": [], "errors": errors},
                artifacts=artifacts,
            )

        existing_fields = data_store.list_table_fields("对标作品库")
        filtered_rows = [
            {
                key: _normalize_store_field_value(key, value)
                for key, value in _map_fields(row, BENCHMARK_POST_STORE_FIELD_MAP).items()
                if key in existing_fields
            }
            for row in collected_rows
        ]
        filtered_rows = [row for row in filtered_rows if row]
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入对标作品库")
        data_store.write_table("对标作品库", filtered_rows, mode="replace")
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"row_count": len(filtered_rows), "error_count": len(errors)},
            payload={"rows": filtered_rows},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入对标作品库",
            detail={"row_count": len(filtered_rows), "error_count": len(errors)},
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"rows": filtered_rows, "errors": errors},
            artifacts=[
                *store_snapshot,
                write_artifact(runtime, step_id, "benchmark_posts.json", filtered_rows),
                write_artifact(runtime, step_id, "tikhub_payloads.json", raw_payloads),
                write_artifact(runtime, step_id, "errors.json", errors),
            ],
            message=f"已抓取并写入 {len(filtered_rows)} 条对标作品",
        )

    return node


def daily_hotspots(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-05-daily-hotspots"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        fetch_started = log_timed_step(runtime, step_id=step_id, phase="hotspot_fetch", message="开始抓取每日热点")
        try:
            normalized = fetch_daily_hotspots_from_step(
                runtime.root,
                DAILY_HOTSPOT_STEP_CONFIG,
                tenant_config=runtime.tenant_runtime_config,
            )
        except urllib.error.HTTPError as exc:
            failure_snapshot = write_failure_snapshot(
                runtime,
                step_id=step_id,
                phase="hotspot_fetch",
                error=f"HTTP {exc.code}",
                detail={"status_code": exc.code},
            )
            fail_timed_step(
                runtime,
                step_id=step_id,
                phase="hotspot_fetch",
                started_at=fetch_started,
                message="每日热点接口调用失败",
                detail={"status_code": exc.code},
                level="warning",
            )
            return soft_fail_state(
                runtime,
                state,
                step_id=step_id,
                message=f"热点接口调用失败：HTTP {exc.code}，已按非阻塞失败继续流程",
                output={"rows": [], "error": f"HTTP {exc.code}"},
                artifacts=failure_snapshot,
            )
        fetch_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="hotspot_fetch",
            detail={"row_count": len(normalized)},
            payload={"rows": normalized},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="hotspot_fetch",
            started_at=fetch_started,
            message="每日热点抓取完成",
            detail={"row_count": len(normalized)},
        )
        data_store = runtime.store()
        merged = merge_hotspot_rows(data_store.read_table("每日热点"), normalized)
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入每日热点")
        data_store.write_table("每日热点", merged["merged_rows"], mode="replace")
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail=merged["summary"],
            payload={"rows": merged["merged_rows"]},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入每日热点",
            detail=merged["summary"],
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={**merged["summary"], "rows": merged["rows"]},
            artifacts=[
                *fetch_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "normalized_hotspots.json", normalized),
                write_artifact(runtime, step_id, "collection_summary.json", merged["summary"]),
            ],
            message=f"已刷新写入 {merged['summary']['row_count']} 条每日热点",
        )

    return node


def marketing_plan(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-06-marketing-plan"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        customers = data_store.read_table("客户背景资料")
        products = data_store.read_table("产品库")
        report = data_store.read_doc("行业报告")
        benchmarks = data_store.read_table("对标作品库")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取营销策划方案生成输入",
            detail={
                "customers": len(customers),
                "products": len(products),
                "has_industry_report": bool(report),
                "benchmark_posts": len(benchmarks),
            },
        )
        values = {
            "today": runtime.batch_id,
            "brand": first_table_value(customers, "品牌名称", default="品牌"),
            "industry": first_table_value(customers, "行业", default="行业"),
            "product_name": first_table_value(products, "产品名称", default="产品"),
            "audience": first_table_value(products, "目标人群", default="目标人群"),
            "customers": customers,
            "products": products,
            "industry_report": report,
            "benchmark_posts": benchmarks,
        }
        generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成营销策划方案")
        result = generate_marketing_plan(runtime.root, values, tenant_config=runtime.tenant_runtime_config)
        plan = result.value
        generation_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="generation",
            detail={"content_length": len(plan)},
            payload={"content": plan},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="generation",
            started_at=generation_started,
            message="营销策划方案生成完成",
            detail={"content_length": len(plan)},
        )
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入营销策划方案")
        data_store.write_doc("营销策划方案", plan)
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"doc_name": "营销策划方案"},
            payload={"content": plan},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入营销策划方案",
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"content": plan},
            artifacts=[
                *generation_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
            ],
            message="已生成营销策划方案",
        )

    return node


def keyword_matrix(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-07-keyword-matrix"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        plan = runtime.store().read_doc("营销策划方案")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取关键词矩阵生成输入",
            detail={"has_marketing_plan": bool(plan)},
        )
        if not plan:
            return block_state(runtime, state, "缺少营销策划方案输入")
        generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成关键词矩阵")
        result = generate_keyword_matrix(
            runtime.root,
            {"today": runtime.batch_id, "marketing_plan": plan},
            tenant_config=runtime.tenant_runtime_config,
        )
        matrix = result.value
        generation_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="generation",
            detail={"content_length": len(matrix)},
            payload={"content": matrix},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="generation",
            started_at=generation_started,
            message="关键词矩阵生成完成",
            detail={"content_length": len(matrix)},
        )
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入关键词矩阵")
        runtime.store().write_doc("关键词矩阵", matrix)
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"doc_name": "关键词矩阵"},
            payload={"content": matrix},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入关键词矩阵",
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"content": matrix},
            artifacts=[
                *generation_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
            ],
            message="已生成关键词矩阵",
        )

    return node


def topic_bank(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        step_id = "collect-08-topic-bank"
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        products = data_store.read_table("产品库")
        plan = data_store.read_doc("营销策划方案")
        report = data_store.read_doc("行业报告")
        log_node_step(
            runtime,
            step_id=step_id,
            event="input_loaded",
            message="已读取选题库生成输入",
            detail={
                "products": len(products),
                "has_marketing_plan": bool(plan),
                "has_industry_report": bool(report),
            },
        )
        if not plan or not report:
            return block_state(runtime, state, "缺少营销策划方案或行业报告输入")
        values = {
            "product_name": first_table_value(products, "产品名称", default="产品"),
            "audience": first_table_value(products, "目标人群", default="目标人群"),
            "marketing_plan": plan,
            "industry_report": report,
        }
        generation_started = log_timed_step(runtime, step_id=step_id, phase="generation", message="开始生成选题库")
        result = generate_topic_bank(runtime.root, values, tenant_config=runtime.tenant_runtime_config)
        rows = result.value
        generation_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="generation",
            detail={"topic_count": len(rows)},
            payload={"rows": rows},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="generation",
            started_at=generation_started,
            message="选题库生成完成",
            detail={"topic_count": len(rows)},
        )
        filtered_rows = [_map_fields(row, TOPIC_STORE_FIELD_MAP) for row in rows if isinstance(row, dict)]
        write_started = log_timed_step(runtime, step_id=step_id, phase="store_write", message="开始写入选题库")
        data_store.write_table("选题库", filtered_rows, mode="replace")
        store_snapshot = write_stage_snapshot(
            runtime,
            step_id=step_id,
            phase="store_write",
            detail={"row_count": len(filtered_rows)},
            payload={"rows": filtered_rows},
        )
        finish_timed_step(
            runtime,
            step_id=step_id,
            phase="store_write",
            started_at=write_started,
            message="已写入选题库",
            detail={"row_count": len(filtered_rows)},
        )
        return persist_step_output(
            runtime,
            state,
            step_id=step_id,
            output={"topics": filtered_rows},
            artifacts=[
                *generation_snapshot,
                *store_snapshot,
                write_artifact(runtime, step_id, "prompt.md", build_message_trace(result.messages)),
            ],
            message=f"已生成 {len(filtered_rows)} 条选题库记录",
        )

    return node
