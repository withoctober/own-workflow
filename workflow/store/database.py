from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from model import (
    get_store_entry,
    insert_store_rows,
    list_store_entries,
    soft_delete_store_entries,
    update_store_rows,
    upsert_store_doc,
)
from workflow.store.base import StoreError, normalize_doc_mode, normalize_table_mode
from workflow.runtime.tenant import TenantRuntimeConfig


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_key: str
    name: str
    kind: str
    fields: tuple[str, ...] = ()


DATASETS: dict[str, DatasetDefinition] = {
    "客户背景资料": DatasetDefinition(
        dataset_key="customer_profiles",
        name="客户背景资料",
        kind="table",
        fields=(
            "品牌名称",
            "行业",
            "门店数量",
            "品牌成立时间",
            "品牌介绍",
            "企业介绍",
            "小红书品牌账号链接",
            "当前经营目标",
            "目标成交渠道",
            "当前渠道结构",
            "是否有线下门店/加盟门店",
            "区域分布",
            "团队人数",
            "预算范围",
            "过往营销动作",
        ),
    ),
    "产品库": DatasetDefinition(
        dataset_key="products",
        name="产品库",
        kind="table",
        fields=(
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
            "竞品定位",
            "竞品解决痛点",
            "竞品使用场景",
            "竞品市场地位",
            "竞品详细介绍",
            "利润空间",
            "是否新品/老品/升级款",
            "复购属性",
            "决策周期",
            "是否高敏感度产品",
            "核心成分或技术",
            "售后高频问题",
            "不适合人群",
        ),
    ),
    "对标账号库": DatasetDefinition(
        dataset_key="benchmark_accounts",
        name="对标账号库",
        kind="table",
        fields=(
            "主页链接",
            "账号名称",
            "配图链接",
            "头像链接",
            "粉丝数",
            "账号简介",
            "标签",
            "地区",
            "认证信息",
            "小红书号",
            "点赞收藏数",
            "互动率",
            "账号定位",
            "高频选题",
            "互动区问题类型",
            "转化动作",
        ),
    ),
    "关键词及行业关键词": DatasetDefinition(
        dataset_key="industry_keywords",
        name="关键词及行业关键词",
        kind="table",
        fields=("关键词", "行业关键词"),
    ),
    "行业报告": DatasetDefinition(dataset_key="industry_report", name="行业报告", kind="doc"),
    "对标作品库": DatasetDefinition(
        dataset_key="benchmark_posts",
        name="对标作品库",
        kind="table",
        fields=("笔记链接", "作者名", "标题", "正文", "标签", "点赞数", "收藏数", "分享数", "配图链接", "封面链接", "发布时间", "提取时间", "报错信息"),
    ),
    "每日热点": DatasetDefinition(
        dataset_key="daily_hotspots",
        name="每日热点",
        kind="table",
        fields=("日期", "热榜标题", "热点来源", "热度值", "榜单标签", "榜单类型", "排名变化", "热点ID", "榜单ID", "图标链接", "标题图片链接"),
    ),
    "营销策划方案": DatasetDefinition(dataset_key="marketing_plan", name="营销策划方案", kind="doc"),
    "关键词矩阵": DatasetDefinition(dataset_key="keyword_matrix", name="关键词矩阵", kind="doc"),
    "选题库": DatasetDefinition(
        dataset_key="topic_bank",
        name="选题库",
        kind="table",
        fields=("爆款标题", "具体场景", "用户痛点", "解决方案", "小红书种草价值点", "小红书选题思路"),
    ),
    "日报": DatasetDefinition(
        dataset_key="daily_reports",
        name="日报",
        kind="table",
        fields=("日期", "今日选题", "内容类型", "标题说明", "正文说明", "封面及配图说明"),
    ),
    "生成作品库": DatasetDefinition(
        dataset_key="generated_works",
        name="生成作品库",
        kind="table",
        fields=("生成日期", "标题", "正文", "标签", "封面提示词", "封面链接", "配图提示词", "配图链接", "报错信息"),
    ),
    "数据分析": DatasetDefinition(
        dataset_key="analytics",
        name="数据分析",
        kind="table",
        fields=("日期", "对象类型", "对象名称", "标题", "阅读量", "点赞数", "收藏数", "评论数", "分享数", "互动量", "互动率", "转化动作", "分析结论"),
    ),
}

DATASETS_BY_KEY: dict[str, DatasetDefinition] = {
    dataset.dataset_key: dataset for dataset in DATASETS.values()
}


def list_table_dataset_definitions() -> list[DatasetDefinition]:
    return [dataset for dataset in DATASETS.values() if dataset.kind == "table"]


def get_table_dataset_definition(dataset_key: str) -> DatasetDefinition | None:
    dataset = DATASETS_BY_KEY.get(str(dataset_key).strip())
    if dataset is None or dataset.kind != "table":
        return None
    return dataset


class DatabaseStore:
    """Database-backed store adapter based on the shared model CRUD layer."""

    def __init__(self, tenant_config: TenantRuntimeConfig) -> None:
        self.tenant_config = tenant_config
        self.database_url = tenant_config.database_url
        self.tenant_id = tenant_config.tenant_id
        if not self.database_url:
            raise StoreError("DatabaseStore 缺少 database_url 运行配置")
        if not self.tenant_id:
            raise StoreError("DatabaseStore 缺少 tenant_id 运行配置")

    def read_table(self, name: str) -> list[dict[str, Any]]:
        dataset = self._require_dataset(name, expected_kind="table")
        entries = list_store_entries(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="row",
        )
        rows: list[dict[str, Any]] = []
        for entry in entries:
            row = {"record_id": entry.record_key}
            row.update(entry.payload)
            rows.append(row)
        return rows

    def list_table_fields(self, name: str) -> list[str]:
        dataset = self._require_dataset(name, expected_kind="table")
        return list(dataset.fields)

    def write_table(self, name: str, records: list[dict[str, Any]], mode: str = "replace") -> str:
        dataset = self._require_dataset(name, expected_kind="table")
        normalized_mode = normalize_table_mode(mode)
        filtered = [record for record in records if isinstance(record, dict)]
        if normalized_mode == "replace":
            soft_delete_store_entries(
                self.database_url,
                tenant_id=self.tenant_id,
                dataset_key=dataset.dataset_key,
                entry_type="row",
            )
        insert_store_rows(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            rows=filtered,
        )
        return f"db://{self.tenant_id}/{dataset.dataset_key}"

    def update_table_records(self, name: str, records: list[dict[str, Any]]) -> str:
        dataset = self._require_dataset(name, expected_kind="table")
        update_store_rows(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            rows=[record for record in records if isinstance(record, dict)],
        )
        return f"db://{self.tenant_id}/{dataset.dataset_key}"

    def delete_table(self, name: str) -> str:
        dataset = self._require_dataset(name, expected_kind="table")
        soft_delete_store_entries(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="row",
        )
        return f"db://{self.tenant_id}/{dataset.dataset_key}"

    def read_doc(self, name: str) -> str:
        dataset = self._require_dataset(name, expected_kind="doc")
        entry = get_store_entry(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="doc",
            record_key="__doc__",
        )
        return entry.content_text if entry is not None else ""

    def write_doc(self, name: str, content: str, mode: str = "replace") -> str:
        dataset = self._require_dataset(name, expected_kind="doc")
        normalized_mode = normalize_doc_mode(mode)
        final_content = content
        if normalized_mode == "append":
            existing = self.read_doc(name)
            final_content = f"{existing.rstrip()}\n\n{content}".strip() if existing else content
        upsert_store_doc(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            content_text=final_content,
            title=dataset.name,
        )
        return f"db://{self.tenant_id}/{dataset.dataset_key}"

    def delete_doc(self, name: str) -> str:
        dataset = self._require_dataset(name, expected_kind="doc")
        soft_delete_store_entries(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="doc",
        )
        return f"db://{self.tenant_id}/{dataset.dataset_key}"

    def target_exists(self, name: str) -> bool:
        dataset = self._require_dataset(name)
        entry_type = "doc" if dataset.kind == "doc" else "row"
        entries = list_store_entries(
            self.database_url,
            tenant_id=self.tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type=entry_type,
        )
        return bool(entries)

    @staticmethod
    def _require_dataset(name: str, expected_kind: str | None = None) -> DatasetDefinition:
        dataset = DATASETS.get(name)
        if dataset is None:
            raise StoreError(f"DatabaseStore 未定义数据集: {name}")
        if expected_kind and dataset.kind != expected_kind:
            raise StoreError(f"数据集类型不匹配: {name} 不是 {expected_kind}")
        return dataset
