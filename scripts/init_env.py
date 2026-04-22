from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

ENV_PROMPTS: list[tuple[str, str]] = [
    ("ARK_API_KEY", "1. 请输入火山方舟API Key"),
    ("TIKHUB_API_KEY", "2. 请输入TikHub Key"),
    ("OPENAI_BASE_URL", "3. 请输入LLM BaseURL"),
    ("OPENAI_MODEL", "4. 请输出LLM Model"),
    ("OPENAI_API_KEY", "5. 请输出LLM API Key"),
]


def main() -> int:
    print(f"准备初始化环境变量，目标文件: {ENV_PATH}")
    values = {key: prompt_required(message) for key, message in ENV_PROMPTS}
    write_env_values(ENV_PATH, values)
    print("环境变量已更新:")
    for key, _ in ENV_PROMPTS:
        print(f"  - {key}")
    return 0


def prompt_required(message: str) -> str:
    while True:
        try:
            value = input(f"{message}: ").strip()
        except EOFError as exc:
            raise SystemExit("\n输入已中断，初始化未完成。") from exc
        except KeyboardInterrupt as exc:
            raise SystemExit("\n用户已取消初始化。") from exc
        if value:
            return value
        print("输入不能为空，请重新输入。")


def write_env_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rendered = {key: render_env_assignment(key, value) for key, value in values.items()}
    pending_keys = set(values)
    new_lines: list[str] = []

    for line in lines:
        replaced = False
        for key in list(pending_keys):
            if is_env_assignment_for(line, key):
                new_lines.append(rendered[key])
                pending_keys.remove(key)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)

    if pending_keys:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        for key, _ in ENV_PROMPTS:
            if key in pending_keys:
                new_lines.append(rendered[key])

    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def render_env_assignment(key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
    return f'{key}="{escaped}"'


def is_env_assignment_for(line: str, key: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        return False
    current_key, _ = line.split("=", 1)
    return current_key.strip() == key


if __name__ == "__main__":
    raise SystemExit(main())
