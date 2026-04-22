from __future__ import annotations

from pathlib import Path


def env_value(name: str, root: Path) -> str | None:
    value = __import__("os").environ.get(name)
    if value:
        return value
    env_file = root / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == name:
            return raw.strip().strip("'\"")
    return None
