from __future__ import annotations

import os
from pathlib import Path


REQUIRED_CONFIG_WARNINGS = [
    ("DEEPSEEK_API_KEY", "缺少 DEEPSEEK_API_KEY，LLM 增强模式不可用；只使用本地稳定模型。"),
]

MISSING_REQUIRED: list[str] = []


def load_local_env(project_root: Path | None = None) -> None:
    global MISSING_REQUIRED
    root = project_root or Path(__file__).resolve().parents[1]
    for filename in (".env", ".env.local"):
        path = root / filename
        if not path.exists():
            continue
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=False)
        except Exception:
            load_env_file_fallback(path)

    # Emit warnings for missing optional config
    MISSING_REQUIRED = []
    for key, msg in REQUIRED_CONFIG_WARNINGS:
        if not os.getenv(key):
            MISSING_REQUIRED.append(msg)


def warn_missing_config() -> list[str]:
    """Return a list of missing-config warnings (not fatal)."""
    return list(MISSING_REQUIRED)


def load_env_file_fallback(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
