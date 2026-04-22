from __future__ import annotations

from workflow.flow.daily_report.nodes import generate_daily_report


def build_daily_report_graph(runtime):
    return {
        "entrypoint": "daily-report-01-generate",
        "terminal": "daily-report-01-generate",
        "nodes": {
            "daily-report-01-generate": generate_daily_report(runtime),
        },
        "edges": [],
    }
