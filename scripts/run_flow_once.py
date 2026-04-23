from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.model import get_feishu_runtime_config
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a workflow once for a tenant using local project configuration."
    )
    parser.add_argument("--flow-id", required=True, help="Workflow ID, for example content-collect.")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID, for example default.")
    parser.add_argument("--batch-id", default="", help="Optional batch id override.")
    parser.add_argument("--source-url", default="", help="Optional source URL for flows that need it.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = WorkflowSettings.from_root(root)
    runtime_payload = get_feishu_runtime_config(settings.database_url, args.tenant_id)
    if runtime_payload is None:
        print(f"tenant runtime config not found: {args.tenant_id}", file=sys.stderr)
        return 1

    batch_id = args.batch_id.strip() or datetime.now().strftime("%Y%m%d%H%M%S")
    runtime = GraphRuntime(settings)
    result = runtime.run(
        RunRequest(
            flow_id=args.flow_id,
            tenant_id=args.tenant_id,
            batch_id=batch_id,
            source_url=args.source_url,
            tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
        )
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
