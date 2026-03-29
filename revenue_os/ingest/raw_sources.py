from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import EXTRACTED_ROOT, RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT


RAW_CACHE = EXTRACTED_ROOT / "all_xlsx_raw.json"
BUSINESS_FULL = EXTRACTED_ROOT / "business_data_full.json"


class RawSourceUnavailable(RuntimeError):
    pass


_RAW_CACHE_DATA: dict[str, Any] | None = None
_BUSINESS_FULL_DATA: dict[str, Any] | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def raw_cache() -> dict[str, Any]:
    global _RAW_CACHE_DATA
    if _RAW_CACHE_DATA is None:
        if not RAW_CACHE.exists():
            raise RawSourceUnavailable(f"Raw cache missing: {RAW_CACHE}")
        _RAW_CACHE_DATA = _load_json(RAW_CACHE)
    return _RAW_CACHE_DATA


def business_full() -> dict[str, Any]:
    global _BUSINESS_FULL_DATA
    if _BUSINESS_FULL_DATA is None:
        if not BUSINESS_FULL.exists():
            raise RawSourceUnavailable(f"Business full extract missing: {BUSINESS_FULL}")
        _BUSINESS_FULL_DATA = _load_json(BUSINESS_FULL)
    return _BUSINESS_FULL_DATA


def latest_files(subdir: str) -> list[Path]:
    manual = sorted((RAW_SOURCE_ROOT / subdir).glob("*.xlsx"))
    automated = sorted((RAW_SOURCE_AUTO_ROOT / subdir).glob("*.xlsx"))
    return sorted(manual + automated)


def cache_workbook(relative_fragment: str) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    data = raw_cache()
    matches = sorted(key for key in data if relative_fragment in key)
    if not matches:
        return None, None
    key = matches[-1]
    return key, data[key]


def sheet_sample(relative_fragment: str) -> dict[str, Any]:
    key, workbook = cache_workbook(relative_fragment)
    if key is None or workbook is None:
        raise RawSourceUnavailable(f"Workbook not found for {relative_fragment}")
    sheet_name = next(iter(workbook))
    sheet = workbook[sheet_name]
    sample = sheet.get("sample", []) if isinstance(sheet, dict) else []
    return {
        "cache_key": key,
        "sheet_name": sheet_name,
        "rows": sheet.get("rows") if isinstance(sheet, dict) else len(sample),
        "sample": sample,
        "parser_mode": "raw_cache",
    }


def business_full_view() -> dict[str, Any]:
    return business_full()
