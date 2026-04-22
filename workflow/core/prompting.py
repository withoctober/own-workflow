from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

PROMPTS_ROOT = Path(".")


def read_template(root: Path, relative_path: str) -> str:
    path = root / relative_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def read_prompt(root: Path, relative_path: str) -> str:
    return read_template(root, str(PROMPTS_ROOT / relative_path))


def render_template(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(values.get(key, ""))

    return re.sub(r"\{\{\s*([^{}]+)\s*\}\}", replace, template)


def render_prompt(root: Path, relative_path: str, values: dict[str, Any]) -> str:
    return render_template(read_prompt(root, relative_path), values)


def split_prompt_values(
    values: dict[str, Any],
    template_keys: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    template_key_set = set(template_keys)
    template_values = {key: value for key, value in values.items() if key in template_key_set}
    context_values = {key: value for key, value in values.items() if key not in template_key_set}
    return template_values, context_values


def prepare_prompt_inputs(
    root: Path,
    relative_path: str,
    values: dict[str, Any],
    *,
    template_keys: Iterable[str] = (),
) -> tuple[str, dict[str, Any]]:
    template_values, context_values = split_prompt_values(values, template_keys)
    prompt = render_template(read_prompt(root, relative_path), template_values)
    return prompt, context_values


__all__ = [
    "PROMPTS_ROOT",
    "prepare_prompt_inputs",
    "read_prompt",
    "read_template",
    "render_prompt",
    "render_template",
    "split_prompt_values",
]
