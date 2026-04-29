import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class ExternalAPIError(Exception):
    source: str
    kind: str
    message: str
    attempts: int = 0

    def __str__(self) -> str:
        return f"{self.source} {self.kind}: {self.message} ({self.attempts} attempts)"


def get_json_with_retry(
    url: str,
    *,
    source: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 12,
    retries: int = 2,
    backoff_seconds: float = 0.8,
) -> dict | list:
    """HTTP GET with small retry/backoff and clean error categories for external APIs."""
    attempts = retries + 1
    last_kind = "unknown"
    last_message = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code in {408, 425, 429, 500, 502, 503, 504} and attempt < attempts:
                last_kind = "rate_limit" if response.status_code == 429 else "temporary_http"
                last_message = f"HTTP {response.status_code}"
                logger.warning("%s temporary error %s, retry %s/%s", source, response.status_code, attempt, attempts)
                time.sleep(backoff_seconds * attempt)
                continue
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            last_kind = "timeout"
            last_message = str(exc) or "request timed out"
        except requests.ConnectionError as exc:
            last_kind = "connection"
            last_message = str(exc) or "connection error"
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            last_kind = "rate_limit" if status == 429 else "http"
            last_message = f"HTTP {status}" if status else str(exc)
        except ValueError as exc:
            last_kind = "invalid_json"
            last_message = str(exc) or "invalid JSON response"

        logger.warning("%s request failed: %s (%s/%s)", source, last_kind, attempt, attempts)
        if attempt < attempts:
            time.sleep(backoff_seconds * attempt)

    raise ExternalAPIError(source=source, kind=last_kind, message=last_message, attempts=attempts)
