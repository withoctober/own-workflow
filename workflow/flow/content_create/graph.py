from __future__ import annotations

from workflow.flow.content_create.nodes import (
    original_copy,
    original_images,
    rewrite_copy,
    rewrite_fetch,
    rewrite_images,
)


def build_content_create_original_graph(runtime):
    return {
        "entrypoint": "create-original-01-copy",
        "terminal": "create-original-02-images",
        "nodes": {
            "create-original-01-copy": original_copy(runtime),
            "create-original-02-images": original_images(runtime),
        },
        "edges": [("create-original-01-copy", "create-original-02-images")],
    }


def build_content_create_rewrite_graph(runtime):
    return {
        "entrypoint": "create-rewrite-01-fetch",
        "terminal": "create-rewrite-03-images",
        "nodes": {
            "create-rewrite-01-fetch": rewrite_fetch(runtime),
            "create-rewrite-02-copy": rewrite_copy(runtime),
            "create-rewrite-03-images": rewrite_images(runtime),
        },
        "edges": [
            ("create-rewrite-01-fetch", "create-rewrite-02-copy"),
            ("create-rewrite-02-copy", "create-rewrite-03-images"),
        ],
    }
