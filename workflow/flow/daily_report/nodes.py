from __future__ import annotations

from typing import Any

from workflow.flow.common import block_state, persist_step_output, skip_if_blocked, write_artifact
from workflow.core.text import truncate_text
from workflow.runtime.context import RuntimeContext
from workflow.core.ai import build_message_trace
from workflow.flow.daily_report.generation import generate_daily_report_record
from workflow.store import StoreError


DAILY_REPORT_STORE_FIELD_MAP = {
    "today_topic": "今日选题",
    "content_type": "内容类型",
    "title_notes": "标题说明",
    "body_notes": "正文说明",
    "cover_and_image_notes": "封面及配图说明",
}


def _compact_records(records: list[dict[str, Any]], limit: int, max_value_chars: int = 1200) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for record in records[:limit]:
        compacted.append(
            {
                key: truncate_text(str(value), max_value_chars, suffix="...[TRUNCATED]")
                for key, value in record.items()
                if key != "record_id" and value is not None and str(value).strip()
            }
        )
    return compacted


def generate_daily_report(runtime: RuntimeContext):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        skipped = skip_if_blocked(state)
        if skipped is not None:
            return skipped
        data_store = runtime.store()
        marketing_plan = data_store.read_doc("营销策划方案")
        keyword_matrix = data_store.read_doc("关键词矩阵")
        topic_bank = data_store.read_table("选题库")
        hotspots = data_store.read_table("每日热点")
        history_reports = data_store.read_table("日报")
        try:
            analytics = data_store.read_table("数据分析")
        except StoreError:
            analytics = []

        missing = []
        if not marketing_plan:
            missing.append("营销策划方案")
        if not keyword_matrix:
            missing.append("关键词矩阵")
        if not topic_bank:
            missing.append("选题库")
        if missing:
            return block_state(runtime, state, f"缺少日报生成依赖: {', '.join(missing)}")

        values = {
            "today": runtime.batch_id,
            "marketing_plan": truncate_text(marketing_plan, 20000, suffix="\n\n[TRUNCATED]"),
            "keyword_matrix": truncate_text(keyword_matrix, 12000, suffix="\n\n[TRUNCATED]"),
            "topic_bank": _compact_records(topic_bank, 20),
            "today_hotspots": _compact_records(hotspots, 20),
            "history_reports": _compact_records(history_reports, 7) or "历史日报暂无可用输入",
            "analytics": _compact_records(analytics, 14) or "数据分析暂无可用输入",
        }
        result = generate_daily_report_record(runtime.root, values)
        payload = result.value
        record = {"日期": runtime.batch_id}
        for source_key, target_key in DAILY_REPORT_STORE_FIELD_MAP.items():
            value = str(payload.get(source_key, "")).strip()
            if not value:
                return block_state(runtime, state, f"日报输出缺少字段: {target_key}")
            record[target_key] = value
        data_store.write_table("日报", [record], mode="append_latest")
        return persist_step_output(
            runtime,
            state,
            step_id="daily-report-01-generate",
            output=payload,
            artifacts=[
                write_artifact(runtime, "daily-report-01-generate", "prompt.md", build_message_trace(result.messages)),
                write_artifact(runtime, "daily-report-01-generate", "daily_report.json", payload),
            ],
            message="已生成日报",
        )

    return node
