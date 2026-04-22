from __future__ import annotations

from workflow.flow.content_collect import nodes


def build_content_collect_graph(runtime):
    return {
        "entrypoint": "collect-01-coordinator-check",
        "terminal": "collect-08-topic-bank",
        "nodes": {
            "collect-01-coordinator-check": nodes.coordinator_check(runtime),
            "collect-02-industry-keywords": nodes.industry_keywords(runtime),
            "collect-03-industry-report": nodes.industry_report(runtime),
            "collect-04-benchmark-posts": nodes.benchmark_posts(runtime),
            "collect-05-daily-hotspots": nodes.daily_hotspots(runtime),
            "collect-06-marketing-plan": nodes.marketing_plan(runtime),
            "collect-07-keyword-matrix": nodes.keyword_matrix(runtime),
            "collect-08-topic-bank": nodes.topic_bank(runtime),
        },
        "edges": [
            ("collect-01-coordinator-check", "collect-02-industry-keywords"),
            ("collect-02-industry-keywords", "collect-03-industry-report"),
            ("collect-03-industry-report", "collect-04-benchmark-posts"),
            ("collect-04-benchmark-posts", "collect-05-daily-hotspots"),
            ("collect-05-daily-hotspots", "collect-06-marketing-plan"),
            ("collect-06-marketing-plan", "collect-07-keyword-matrix"),
            ("collect-07-keyword-matrix", "collect-08-topic-bank"),
        ],
    }
