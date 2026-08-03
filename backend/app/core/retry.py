"""Small bounded retry helper for transient infrastructure failures."""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


def run_with_retry(
    operation: Callable[[], T],
    *,
    operation_name: str,
    attempts: int,
    is_retriable: Callable[[Exception], bool],
) -> T:
    """Run a synchronous operation with bounded exponential backoff."""
    bounded_attempts = max(1, min(attempts, 5))
    for attempt in range(1, bounded_attempts + 1):
        try:
            return operation()
        except Exception as exception:
            if attempt >= bounded_attempts or not is_retriable(exception):
                raise
            delay_seconds = min(0.25 * (2 ** (attempt - 1)), 2.0)
            logger.warning(
                "Transient infrastructure failure operation=%s attempt=%s",
                operation_name,
                attempt,
            )
            time.sleep(delay_seconds)

    raise RuntimeError("Retry loop ended unexpectedly.")
