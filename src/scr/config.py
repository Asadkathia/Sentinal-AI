from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = {
    "fail_on": "HIGH",
    "max_findings_total": 12,
    "max_findings_per_file": 3,
    "enable_llm": "auto",
    "llm_provider": "gemini",
    "llm_model": "gemini-2.0-flash",
    "redact_patterns": [
        r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)bearer\s+[A-Za-z0-9_\-.=]{12,}",
    ],
    "exclude_globs": ["dist/**", "build/**", "**/*.min.js", "vendor/**"],
    "tool_commands": {
        "python": ["ruff check .", "pytest -q"],
        "node": ["npm run lint", "npm test -- --watch=false"],
        "go": ["go vet ./...", "go test ./..."],
    },
}


class ConfigError(Exception):
    pass


def default_config_path(cwd: str | Path | None = None) -> Path:
    root = Path(cwd or Path.cwd())
    return root / ".smartreview.yml"


def write_default_config(path: Path) -> None:
    path.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")


def load_config(cwd: str | Path | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    cfg_path = default_config_path(cwd)
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        config = deep_merge(config, raw)

    env_provider = os.getenv("SCR_LLM_PROVIDER")
    env_model = os.getenv("SCR_LLM_MODEL")
    if env_provider:
        config["llm_provider"] = env_provider
    if env_model:
        config["llm_model"] = env_model

    return config


def llm_enabled(config: dict[str, Any], no_llm: bool) -> bool:
    if no_llm:
        return False
    mode = str(config.get("enable_llm", "auto")).lower()
    provider = str(config.get("llm_provider", "openai")).lower()
    if provider == "disabled":
        return False
    if mode == "false":
        return False
    # Check for a valid API key depending on provider
    if provider == "gemini":
        has_key = bool(os.getenv("SCR_GEMINI_API_KEY"))
    else:
        has_key = bool(os.getenv("SCR_OPENAI_API_KEY"))
    if mode == "true":
        return has_key
    # auto
    return has_key


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out
