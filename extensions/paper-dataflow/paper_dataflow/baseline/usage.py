"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
from typing import Any


USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "reasoning_tokens",
)


_CREDENTIAL_KEYS = {
    "apikey",
    "authorization",
    "authorizationheader",
    "credential",
    "credentials",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "xapikey",
}


_CHAIN_OF_THOUGHT_KEYS = {
    "chainofthought",
    "cot",
    "reasoningcontent",
    "reasoningtext",
    "thinkingcontent",
    "thought",
    "thoughts",
}


def empty_standardized_usage() -> dict[str, int | None]:
    return {field: None for field in USAGE_FIELDS}


def _normalized_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _sensitive_raw_key(key: str) -> str | None:
    normalized = _normalized_key(key)
    if (
        normalized in _CREDENTIAL_KEYS
        or normalized.endswith("apikey")
        or normalized.startswith("authorization")
    ):
        return "CREDENTIAL_FIELD_REMOVED"
    if normalized in _CHAIN_OF_THOUGHT_KEYS:
        return "CHAIN_OF_THOUGHT_FIELD_REMOVED"
    return None


def _safe_raw_value(value: Any, *, issues: list[str], path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [
            _safe_raw_value(item, issues=issues, path=f"{path}[]") for item in value
        ]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            removal = _sensitive_raw_key(key)
            if removal is not None:
                issues.append(f"{removal}:{path}.{key}")
                continue
            result[key] = _safe_raw_value(
                item, issues=issues, path=f"{path}.{key}"
            )
        return result
    issues.append(f"NON_JSON_VALUE_REMOVED:{path}")
    return None


def _token_value(
    usage: dict[str, Any],
    key: str,
    *,
    issues: list[str],
) -> int | None:
    if key not in usage:
        return None
    value = usage[key]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    issues.append(f"INVALID_USAGE_FIELD:{key}")
    return None


def _nested_token_value(
    usage: dict[str, Any],
    parent: str,
    key: str,
    *,
    issues: list[str],
) -> int | None:
    nested = usage.get(parent)
    if nested is None:
        return None
    if not isinstance(nested, dict):
        issues.append(f"INVALID_USAGE_FIELD:{parent}")
        return None
    return _token_value(nested, key, issues=issues)


def observe_provider_usage(raw_usage: Any) -> dict[str, Any]:
    """Map a provider usage object without turning missing values into zero."""
    if not isinstance(raw_usage, dict):
        return {
            "standardized_usage": empty_standardized_usage(),
            "raw_provider_usage": None,
            "usage_observation_status": "NOT_RETURNED",
            "usage_mapping_issues": [],
        }

    issues: list[str] = []
    safe_raw = _safe_raw_value(raw_usage, issues=issues, path="usage")
    standardized = empty_standardized_usage()
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        standardized[key] = _token_value(raw_usage, key, issues=issues)

    cache_hit = _token_value(
        raw_usage, "prompt_cache_hit_tokens", issues=issues
    )
    if cache_hit is None and "prompt_cache_hit_tokens" not in raw_usage:
        cache_hit = _nested_token_value(
            raw_usage, "prompt_tokens_details", "cached_tokens", issues=issues
        )
    standardized["prompt_cache_hit_tokens"] = cache_hit
    standardized["prompt_cache_miss_tokens"] = _token_value(
        raw_usage, "prompt_cache_miss_tokens", issues=issues
    )

    reasoning = _token_value(raw_usage, "reasoning_tokens", issues=issues)
    if reasoning is None and "reasoning_tokens" not in raw_usage:
        reasoning = _nested_token_value(
            raw_usage,
            "completion_tokens_details",
            "reasoning_tokens",
            issues=issues,
        )
    standardized["reasoning_tokens"] = reasoning

    prompt = standardized["prompt_tokens"]
    completion = standardized["completion_tokens"]
    total = standardized["total_tokens"]
    if (
        prompt is not None
        and completion is not None
        and total is not None
        and prompt + completion != total
    ):
        issues.append("USAGE_TOTAL_ARITHMETIC_MISMATCH")
    if all(standardized[field] is not None for field in USAGE_FIELDS):
        status = "OBSERVED_COMPLETE"
    else:
        status = "OBSERVED_PARTIAL"
    return {
        "standardized_usage": standardized,
        "raw_provider_usage": safe_raw,
        "usage_observation_status": status,
        "usage_mapping_issues": sorted(set(issues)),
    }


def no_response_usage_observation() -> dict[str, Any]:
    return {
        "standardized_usage": empty_standardized_usage(),
        "raw_provider_usage": None,
        "usage_observation_status": "NO_RESPONSE",
        "usage_mapping_issues": [],
    }
