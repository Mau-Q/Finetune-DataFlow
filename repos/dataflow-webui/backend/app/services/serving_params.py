"""Translate the WebUI's configs object into DataFlow **kwargs."""

import json


def expand_serving_configs(params: dict) -> dict:
    result = dict(params)
    extra = result.pop("configs", None)
    if extra is None or extra == "":
        return result
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError as exc:
            raise ValueError("Serving configs must be a JSON object") from exc
    if not isinstance(extra, dict):
        raise ValueError("Serving configs must be a JSON object")
    # The dedicated fields remain authoritative for transport and credentials.
    reserved = {"configs", "api_key", "api_url", "key_name_of_api_key", "model_name",
                "temperature", "max_workers", "max_retries", "connect_timeout", "read_timeout"}
    if set(extra) & (reserved | set(result)):
        raise ValueError("Serving configs cannot override dedicated serving fields")
    result.update(extra)
    return result
