from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_POLICY_RULES_PATH = Path(__file__).with_name("default_policy_rules.json")


def load_policy_rules(path: str | Path | None = None) -> dict[str, Any]:
    with DEFAULT_POLICY_RULES_PATH.open("r", encoding="utf-8") as f:
        rules = json.load(f)

    override_path = resolve_override_path(path)
    if override_path and override_path.exists():
        with override_path.open("r", encoding="utf-8") as f:
            rules = deep_merge(rules, json.load(f))
    return rules


def resolve_override_path(path: str | Path | None = None) -> Path | None:
    if path:
        return Path(path)
    env_path = os.getenv("FINTRACE_POLICY_OVERRIDES_PATH")
    if env_path:
        return Path(env_path)
    runtime_path = Path(__file__).resolve().parents[1] / "runtime" / "policy_overrides.json"
    return runtime_path if runtime_path.exists() else None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def expense_limits() -> dict[str, float]:
    raw = load_policy_rules().get("expense_limits", {})
    return {str(key): float(value) for key, value in raw.items()}


def blacklisted_vendor_tokens() -> set[str]:
    return {str(item) for item in load_policy_rules().get("blacklisted_vendor_tokens", [])}


def approval_complete_statuses() -> set[str]:
    return normalize_status_set(load_policy_rules().get("approval_complete_statuses", []))


def approval_incomplete_statuses() -> set[str]:
    return normalize_status_set(load_policy_rules().get("approval_incomplete_statuses", []))


def cold_start_rules() -> dict[str, Any]:
    return load_policy_rules().get("cold_start", {})


def showcase_risk_keywords() -> dict[str, list[str]]:
    raw = load_policy_rules().get("showcase_risk_keywords", {})
    return {str(key): [str(item) for item in value] for key, value in raw.items() if isinstance(value, list)}


def normalize_status_set(values: list[Any]) -> set[str]:
    return {normalize_status(value) for value in values}


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()
