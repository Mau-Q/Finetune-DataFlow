"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
import hashlib, json, socket, threading, time
import urllib.error, urllib.request
from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse
import httpx
from .usage import no_response_usage_observation, observe_provider_usage


class ModelGatewayError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        response_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.request_id = request_id
        self.retryable = retryable
        self.response_metadata = response_metadata


class OpenAICompatibleModelGateway:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout: float = 60.0,
        temperature: float = 0.2,
        response_format: str = "json_object",
        thinking: str | None = None,
        enable_thinking: bool | None = None,
        max_output_tokens: int | None = None,
        transport_retries: int = 0,
        retry_backoff_seconds: float = 0.2,
        candidate_retries: int | None = None,
        transport: Callable | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        if response_format not in {"json_object", "text"}:
            raise ValueError("response_format must be json_object or text")
        if thinking not in {None, "enabled", "disabled"}:
            raise ValueError("thinking must be enabled, disabled, or unset")
        if enable_thinking is not None and not isinstance(enable_thinking, bool):
            raise ValueError("enable_thinking must be a boolean or unset")
        if thinking is not None and enable_thinking is not None:
            raise ValueError("thinking and enable_thinking cannot both be set")
        self.response_format = response_format
        self.thinking = thinking
        self.enable_thinking = enable_thinking
        if max_output_tokens is not None and max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if transport_retries not in {0, 1}:
            raise ValueError("transport_retries must be 0 or 1")
        if candidate_retries is not None and candidate_retries < 0:
            raise ValueError("candidate_retries must be non-negative")
        self.max_output_tokens = max_output_tokens
        self.transport_retries = transport_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.candidate_retries = candidate_retries
        self.transport = transport
        self.usage_totals: Counter[str] = Counter()
        self.call_durations_seconds: list[float] = []
        self.request_ids: list[str] = []
        self.request_count = 0
        self.retry_count = 0
        self.successful_response_count = 0
        self.actual_model_name = model_name
        self.call_records: list[dict[str, Any]] = []
        self._operation_contexts: dict[str, dict[str, Any]] = {}
        self._metrics_lock = threading.Lock()

    def set_call_context(self, operation_id: str, context: dict[str, Any]) -> None:
        safe_fields = {
            key: context.get(key)
            for key in (
                "stage",
                "candidate_id",
                "paper_id",
                "plan_index",
                "semantic_attempt",
                "pricing_snapshot_id",
            )
        }
        with self._metrics_lock:
            self._operation_contexts[operation_id] = safe_fields


    def complete(self, messages: list[dict[str, str]], *, operation_id: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": self.response_format},
        }
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        if self.thinking is not None:
            payload["thinking"] = {"type": self.thinking}
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking
        return self._complete(payload, operation_id=operation_id)

    def connection_test(self, message: str) -> str:
        """Send a minimal non-paper connectivity probe through the configured profile."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": message}],
            "temperature": 0,
            "max_tokens": min(self.max_output_tokens or 32, 32),
        }
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking
        return self._complete(payload, operation_id=None)

    def _complete(self, payload: dict, *, operation_id: str | None) -> str:
        request_body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        request_sha256 = hashlib.sha256(request_body).hexdigest()
        with self._metrics_lock:
            context = dict(self._operation_contexts.get(operation_id or "", {}))
        for attempt in range(self.transport_retries + 1):
            started = perf_counter()
            request_started_at = datetime.now(timezone.utc).isoformat()
            usage_observation = no_response_usage_observation()
            call_record = {
                "operation_id": operation_id,
                "attempt": attempt + 1,
                "transport_attempt": attempt + 1,
                "semantic_attempt": context.get("semantic_attempt", 1),
                "provider": urlparse(self.base_url).hostname,
                "configured_model": self.model_name,
                "stage": context.get("stage"),
                "candidate_id": context.get("candidate_id"),
                "paper_id": context.get("paper_id"),
                "plan_index": context.get("plan_index"),
                "pricing_snapshot_id": context.get("pricing_snapshot_id"),
                "request_started_at": request_started_at,
                "response_received_at": None,
                "latency_ms": None,
                "successful": False,
                "request_id": None,
                "provider_request_id": None,
                "response_id": None,
                "request_sha256": request_sha256,
                "response_sha256": None,
                "usage": {},
                **usage_observation,
                "http_status": None,
                "raw_body": "",
                "system_fingerprint": None,
                "transport_exception_type": None,
                "finish_reason": None,
                "actual_model": None,
                "error_code": None,
            }
            with self._metrics_lock:
                self.request_count += 1
            try:
                content, response_metadata = self._post_payload(payload)
                call_record.update(response_metadata)
                call_record["successful"] = True
            except ModelGatewayError as exc:
                if exc.response_metadata is not None:
                    call_record.update(exc.response_metadata)
                call_record["http_status"] = exc.http_status
                response_received = (
                    (
                        exc.response_metadata is not None
                        and exc.response_metadata.get("response_received", True)
                    )
                    or exc.http_status is not None
                    or exc.code != "MODEL_TRANSPORT_ERROR"
                )
                call_record.update(
                    {
                        "request_id": call_record.get("request_id") or exc.request_id,
                        "provider_request_id": (
                            call_record.get("provider_request_id") or exc.request_id
                        ),
                        "error_code": exc.code,
                    }
                )
                if response_received and call_record.get("response_received_at") is None:
                    call_record["response_received_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                if (
                    response_received
                    and exc.response_metadata is None
                    and call_record["usage_observation_status"] == "NO_RESPONSE"
                ):
                    call_record["usage_observation_status"] = "NOT_RETURNED"
                if not exc.retryable or attempt >= self.transport_retries:
                    raise
                with self._metrics_lock:
                    self.retry_count += 1
                time.sleep(self.retry_backoff_seconds)
            else:
                with self._metrics_lock:
                    self.successful_response_count += 1
                return content
            finally:
                duration = perf_counter() - started
                call_record["duration_seconds"] = round(duration, 6)
                call_record["latency_ms"] = round(duration * 1000, 3)
                with self._metrics_lock:
                    self.call_durations_seconds.append(duration)
                    self.call_records.append(call_record)
        raise AssertionError("unreachable")

    def _post_payload(self, payload: dict) -> tuple[str, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        provider_request_id: str | None = None
        raw_body = ""
        response_status: int | None = None
        if self.transport is None:
            try:
                with httpx.Client(timeout=self.timeout, trust_env=True) as client:
                    response = client.post(url, content=body, headers=headers)
                provider_request_id = self._capture_request_id(response.headers)
                raw_body = response.content.decode("utf-8", errors="replace")
                response_status = response.status_code
                if not 200 <= response.status_code < 300:
                    raise self._http_error(
                        response.status_code,
                        provider_request_id,
                        response_metadata={
                            "http_status": response.status_code,
                            "raw_body": raw_body,
                        },
                    )
                payload = response.json()
            except httpx.TimeoutException as exc:
                raise ModelGatewayError(
                    "MODEL_TRANSPORT_ERROR",
                    "Model service timed out.",
                    retryable=True,
                    response_metadata={
                        "response_received": False,
                        "transport_exception_type": type(exc).__name__,
                    },
                ) from exc
            except httpx.RequestError as exc:
                raise ModelGatewayError(
                    "MODEL_TRANSPORT_ERROR",
                    "Model service request failed.",
                    retryable=True,
                    response_metadata={
                        "response_received": False,
                        "transport_exception_type": type(exc).__name__,
                    },
                ) from exc
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelGatewayError(
                    "MODEL_RESPONSE_ERROR",
                    "Model service response did not match chat completion format.",
                    response_metadata={
                        "response_received": True,
                        "http_status": response_status,
                        "raw_body": raw_body,
                        "response_sha256": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
                    },
                ) from exc
        else:
            http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with self.transport(http_request, timeout=self.timeout) as response:
                    raw_body = response.read().decode("utf-8")
                    payload = json.loads(raw_body)
                    response_status = getattr(response, "status", 200)
            except urllib.error.HTTPError as exc:
                request_id = self._capture_request_id(exc.headers or {})
                raise self._http_error(exc.code, request_id) from exc
            except (TimeoutError, socket.timeout) as exc:
                raise ModelGatewayError("MODEL_TRANSPORT_ERROR", "Model service timed out.", retryable=True) from exc
            except (urllib.error.URLError, OSError) as exc:
                raise ModelGatewayError("MODEL_TRANSPORT_ERROR", "Model service request failed.", retryable=True) from exc
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ModelGatewayError(
                    "MODEL_RESPONSE_ERROR",
                    "Model service response did not match chat completion format.",
                    response_metadata={
                        "response_received": True,
                        "http_status": response_status,
                        "raw_body": raw_body,
                        "response_sha256": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
                    },
                ) from exc
        response_received_at = datetime.now(timezone.utc).isoformat()
        response_sha256 = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if not isinstance(payload, dict):
            raise ModelGatewayError(
                "MODEL_RESPONSE_ERROR",
                "Model service response did not match chat completion format.",
                request_id=provider_request_id,
                response_metadata={
                    "request_id": provider_request_id,
                    "provider_request_id": provider_request_id,
                    "response_received_at": response_received_at,
                    "response_sha256": response_sha256,
                    **observe_provider_usage(None),
                },
            )
        payload_request_id = payload.get("request_id")
        if isinstance(payload_request_id, str) and payload_request_id:
            self._capture_request_id({"x-request-id": payload_request_id})
            provider_request_id = payload_request_id
        payload_response_id = payload.get("id")
        response_id = (
            payload_response_id.strip()
            if isinstance(payload_response_id, str) and payload_response_id.strip()
            else None
        )
        actual_model = payload.get("model")
        if isinstance(actual_model, str) and actual_model.strip():
            actual_model = actual_model.strip()
            with self._metrics_lock:
                self.actual_model_name = actual_model
        else:
            actual_model = None
        usage_observation = observe_provider_usage(payload.get("usage"))
        safe_usage = {
            key: value
            for key, value in usage_observation["standardized_usage"].items()
            if value is not None
        }
        with self._metrics_lock:
            for key, value in safe_usage.items():
                self.usage_totals[key] += value
        response_metadata = {
            "http_status": response_status,
            "raw_body": raw_body,
            "request_id": provider_request_id,
            "provider_request_id": provider_request_id,
            "response_id": response_id,
            "usage": safe_usage,
            **usage_observation,
            "finish_reason": None,
            "actual_model": actual_model,
            "system_fingerprint": (
                payload.get("system_fingerprint")
                if isinstance(payload.get("system_fingerprint"), str)
                else None
            ),
            "response_received_at": response_received_at,
            "response_sha256": response_sha256,
        }
        try:
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelGatewayError(
                "MODEL_RESPONSE_ERROR",
                "Model service response did not contain message content.",
                request_id=provider_request_id,
                response_metadata=response_metadata,
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelGatewayError(
                "MODEL_RESPONSE_ERROR",
                "Model service returned empty content.",
                request_id=provider_request_id,
                response_metadata=response_metadata,
            )
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        response_metadata["finish_reason"] = (
            finish_reason if isinstance(finish_reason, str) else None
        )
        return content, response_metadata

    def latest_call_record(self, operation_id: str) -> dict[str, Any] | None:
        """Return the most recent durable diagnostic record for one operation."""
        with self._metrics_lock:
            for record in reversed(self.call_records):
                if record.get("operation_id") == operation_id:
                    return dict(record)
        return None

    def _capture_request_id(self, headers) -> str | None:
        request_id = None
        for name in ("x-request-id", "x-dashscope-request-id", "request-id"):
            value = headers.get(name) if hasattr(headers, "get") else None
            if isinstance(value, str) and value.strip():
                request_id = value.strip()
                break
        if request_id is not None:
            with self._metrics_lock:
                if request_id not in self.request_ids:
                    self.request_ids.append(request_id)
        return request_id

    @staticmethod
    def _http_error(
        status: int,
        request_id: str | None,
        *,
        response_metadata: dict[str, Any] | None = None,
    ) -> ModelGatewayError:
        if status == 401:
            return ModelGatewayError(
                "AUTHENTICATION_ERROR",
                "Model authentication failed.",
                http_status=status,
                request_id=request_id,
                response_metadata=response_metadata,
            )
        if status == 403:
            return ModelGatewayError(
                "PERMISSION_ERROR",
                "Model permission was denied.",
                http_status=status,
                request_id=request_id,
                response_metadata=response_metadata,
            )
        if status == 404:
            return ModelGatewayError(
                "MODEL_NOT_FOUND",
                "Configured model was not found.",
                http_status=status,
                request_id=request_id,
                response_metadata=response_metadata,
            )
        if status == 429:
            return ModelGatewayError(
                "RATE_LIMIT_ERROR",
                "Model service rate limit was reached.",
                http_status=status,
                request_id=request_id,
                retryable=True,
                response_metadata=response_metadata,
            )
        if 500 <= status <= 599:
            return ModelGatewayError(
                "MODEL_TRANSPORT_ERROR",
                "Model service was temporarily unavailable.",
                http_status=status,
                request_id=request_id,
                retryable=True,
                response_metadata=response_metadata,
            )
        return ModelGatewayError(
            "MODEL_RESPONSE_ERROR",
            "Model service rejected the request.",
            http_status=status,
            request_id=request_id,
            response_metadata=response_metadata,
        )
