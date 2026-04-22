from __future__ import annotations


def truncate_text(text: str, max_chars: int, *, suffix: str = "\n\n[TRUNCATED]") -> str:
    if max_chars <= 0:
        return suffix.strip()
    if len(text) <= max_chars:
        return text
    keep = max_chars - len(suffix)
    if keep <= 0:
        return suffix[:max_chars]
    return text[:keep].rstrip() + suffix
