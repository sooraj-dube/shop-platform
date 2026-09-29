"""Base HTTP client for calling other shop services.

Every service answers errors as ``{"error": {"code": ..., "message": ...}}``. This
client turns those into exceptions and retries requests that are safe to repeat:
GETs, and writes that carry an ``Idempotency-Key``.
"""

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from shop_platform import __version__

logger = logging.getLogger(__name__)


class ServiceUnavailable(Exception):
    """The service could not be reached, timed out, or answered with a 5xx."""


class ServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    pass


class ServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        service_name: str,
        timeout: float = 2.0,
        retries: int = 2,
        backoff: float = 0.2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.service_name = service_name
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": f"shop-platform/{__version__}"},
        )

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        repeatable = method.upper() == "GET" or idempotency_key is not None
        attempts = 1 + (self._retries if repeatable else 0)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._http.request(
                    method, path, json=json, params=params, headers=headers
                )
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code < 500:
                    return self._handle(response)
                last_error = ServiceError(response.status_code, "server_error", response.text[:200])
            logger.warning(
                "request failed",
                extra={
                    "service": self.service_name,
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                    "error": str(last_error),
                },
            )
            if attempt < attempts:
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise ServiceUnavailable(
            f"{self.service_name} unavailable after {attempts} attempt(s): {method} {path}"
        ) from last_error

    def _handle(self, response: httpx.Response) -> Any:
        if response.is_success:
            return response.json() if response.content else None
        code, message = _error_body(response)
        if response.status_code == 404:
            raise NotFound(404, code, message)
        if response.status_code == 409:
            raise Conflict(409, code, message)
        raise ServiceError(response.status_code, code, message)


def _error_body(response: httpx.Response) -> tuple[str, str]:
    try:
        error = response.json()["error"]
        return str(error["code"]), str(error["message"])
    except (ValueError, KeyError, TypeError):
        return "http_error", response.text[:200]
