from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    timeout_seconds: int = 45
    stabilization_seconds: int = 2


def default_retry_policy() -> RetryPolicy:
    timeout_seconds = int(os.environ.get("REVENUE_OS_ACQ_TIMEOUT_SECONDS", "45"))
    stabilization_seconds = int(os.environ.get("REVENUE_OS_ACQ_STABILIZATION_SECONDS", "2"))
    max_attempts = int(os.environ.get("REVENUE_OS_ACQ_MAX_ATTEMPTS", "2"))
    return RetryPolicy(
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        stabilization_seconds=stabilization_seconds,
    )
