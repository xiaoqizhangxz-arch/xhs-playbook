from __future__ import annotations

import hashlib
import re
from typing import Iterable


SAFE_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = SAFE_RE.sub("-", lowered)
    return lowered.strip("-") or "na"


def deterministic_id(prefix: str, *parts: object) -> str:
    normalized = "||".join(str(part) for part in parts)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


def readable_id(prefix: str, *parts: str) -> str:
    joined = "-".join(slugify(part) for part in parts if part)
    if joined:
        return f"{prefix}__{joined}"
    return deterministic_id(prefix, *parts)


def idempotency_key(*parts: object) -> str:
    return hashlib.sha256("||".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def short_hash(parts: Iterable[object]) -> str:
    return hashlib.sha256("||".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]
