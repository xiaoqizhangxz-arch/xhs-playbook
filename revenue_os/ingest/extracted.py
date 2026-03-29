from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from xml.etree import ElementTree as ET

from revenue_os.foundation.config import ARTIFACT_DIRS, CREATOR_AUTO_ROOT, EXTRACTED_ROOT, KNOWLEDGE_PERSKU_ROOT, LE_FOND_CONTENT_START_DATE, USERS_AUTO_ROOT, USERS_ROOT
from revenue_os.foundation.io import object_path, read_json, write_json
from revenue_os.acquisition.creator_capture import latest_creator_capture, latest_creator_export
from revenue_os.ingest.raw_sources import RawSourceUnavailable, business_full_view, latest_files, sheet_sample

FIRST_PARTY_FILES = {
    "monthly_kpi": "monthly_kpi.json",
    "shop_funnel": "shop_funnel.json",
    "refund_analysis": "refund_analysis.json",
    "sku_performance": "sku_performance.json",
    "search_terms": "search_terms.json",
    "channel_performance": "channel_performance.json",
    "user_portrait": "user_portrait.json",
    "posts_enriched": "posts_enriched.json",
    "visual_features_products": "visual_features_products.json",
}

BENCHMARK_FILES = {
    "competitor_benchmarks": "competitor_benchmarks.json",
}


def _load_bundle(file_map: dict[str, str]) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    payload: dict[str, Any] = {}
    missing: list[str] = []
    source_files: dict[str, str] = {}
    for key, file_name in file_map.items():
        path = EXTRACTED_ROOT / file_name
        if path.exists():
            payload[key] = read_json(path)
            source_files[key] = str(path)
        else:
            missing.append(file_name)
    return payload, missing, source_files


def _latest_month(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[-1] if rows else {}


def _search_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda item: (item.get("purchase_cvr", 0), item.get("click_rate", 0), item.get("revenue", 0)), reverse=True)
    return {
        "rows": rows,
        "top_terms": ranked[:10],
        "avg_ctr": mean([float(item.get("click_rate", 0) or 0) for item in rows]) if rows else 0.0,
    }


def _channel_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda item: item.get("revenue", 0), reverse=True)
    return {
        "rows": rows,
        "top_channels": ranked[:10],
    }


def _refund_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = rows[-1] if rows else {}
    return {
        "rows": rows,
        "latest": latest,
        "latest_month": latest.get("_month"),
        "max_refund_rate": max((float(item.get("退款率（支付时间）", 0) or 0) for item in rows), default=0.0),
    }


def _content_summary(posts_enriched: dict[str, Any]) -> dict[str, Any]:
    posts = [post for post in posts_enriched.get("posts", []) if str(post.get("post_dt") or "") >= LE_FOND_CONTENT_START_DATE]
    return {
        "posts": posts,
        "winning_formula": posts_enriched.get("winning_formula", {}),
        "models": posts_enriched.get("models", {}),
        "brand_content_cutoff": LE_FOND_CONTENT_START_DATE,
        "excluded_pre_brand_post_count": max(0, len(posts_enriched.get("posts", [])) - len(posts)),
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except ValueError:
        return None


def _days_since(ts: str | None) -> float | None:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 2)


def _int_from_token(value: str | None) -> int | None:
    if value in (None, "", "-"):
        return None
    text = str(value).strip()
    text = text.replace(",", "").replace("，", "").replace(" ", "")
    if text in {"", "-", "+", "--"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _float_from_token(value: str | None) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip()
    text = text.replace(",", "").replace("，", "").replace(" ", "")
    if text in {"", "-", "+", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _normalize_ocr_text(text: str) -> str:
    normalized = text
    for src, dst in [
        ("⽇", "日"),
        ("⽉", "月"),
        ("⽤", "用"),
        ("⼈", "人"),
        ("⽼", "老"),
        ("⾄", "至"),
        ("⻚", "页"),
    ]:
        normalized = normalized.replace(src, dst)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _latest_user_pdfs(subdir: str, pattern: str) -> list[Path]:
    roots = [USERS_AUTO_ROOT / subdir, USERS_ROOT / subdir]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(path for path in root.glob(pattern) if path.is_file())
    files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return files


def _deal_population_flow_summary() -> dict[str, Any]:
    stage_order = ["认知", "意向", "新客", "老客", "流失"]
    aux_stages = ["粉丝", "群聊"]
    stage_files = _latest_user_pdfs("成交分析", "人群流转-*.pdf")
    if not stage_files:
        return {
            "status": "missing",
            "stages": {},
            "stage_order": stage_order,
            "source_files": [],
            "latest_capture_at": None,
        }

    latest_by_stage: dict[str, Path] = {}
    for path in stage_files:
        stage = path.stem.replace("人群流转-", "").strip()
        if stage and stage not in latest_by_stage:
            latest_by_stage[stage] = path

    stage_metrics: dict[str, dict[str, Any]] = {}
    latest_capture_at = None
    max_ts = 0.0
    data_date = None

    all_stages = stage_order + aux_stages
    for stage, path in latest_by_stage.items():
        raw_text = _extract_pdf_text(path)
        if not raw_text:
            continue
        compact = _normalize_ocr_text(raw_text)
        date_match = re.search(r"数据截[至止]：?(\d{4}-\d{2}-\d{2})", compact)
        if date_match:
            data_date = date_match.group(1)
        stage_pattern = re.compile(r"(认知|意向|新客|老客|流失|粉丝|群聊)(\d[\d,]*)(?:近30日([+-]?\d[\d,]*|-))?")
        for match in stage_pattern.finditer(compact):
            label = match.group(1)
            count = _int_from_token(match.group(2))
            delta = _int_from_token(match.group(3))
            if count is None:
                continue
            existing = stage_metrics.get(label)
            if existing and int(existing.get("source_ts", 0) or 0) > int(path.stat().st_mtime):
                continue
            stage_metrics[label] = {
                "count": count,
                "delta_30d": delta,
                "source_file": str(path),
                "source_ts": path.stat().st_mtime,
            }
        ts = path.stat().st_mtime
        if ts >= max_ts:
            max_ts = ts
            latest_capture_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    for label in all_stages:
        stage_metrics.setdefault(label, {"count": None, "delta_30d": None, "source_file": None, "source_ts": 0})

    awareness = _float_from_token(stage_metrics["认知"]["count"])
    intent = _float_from_token(stage_metrics["意向"]["count"])
    new_customer = _float_from_token(stage_metrics["新客"]["count"])
    returning = _float_from_token(stage_metrics["老客"]["count"])
    churn = _float_from_token(stage_metrics["流失"]["count"])
    fan = _float_from_token(stage_metrics["粉丝"]["count"])
    group_chat = _float_from_token(stage_metrics["群聊"]["count"])

    ratios = {
        "awareness_to_intent_cvr": (intent / awareness) if awareness else None,
        "intent_to_new_cvr": (new_customer / intent) if intent else None,
        "new_to_returning_cvr": (returning / new_customer) if new_customer else None,
        "returning_churn_rate": (churn / (returning + churn)) if (returning is not None and churn is not None and (returning + churn) > 0) else None,
        "new_to_fan_ratio": (fan / new_customer) if (fan is not None and new_customer) else None,
        "fan_to_group_chat_ratio": (group_chat / fan) if (group_chat is not None and fan) else None,
    }

    required_ready = all(stage_metrics.get(name, {}).get("count") is not None for name in stage_order[:4])
    status = "ready" if required_ready else "partial"
    return {
        "status": status,
        "stages": {
            key: {
                "count": stage_metrics[key]["count"],
                "delta_30d": stage_metrics[key]["delta_30d"],
                "source_file": stage_metrics[key]["source_file"],
            }
            for key in all_stages
        },
        "stage_order": stage_order,
        "ratios": ratios,
        "data_date": data_date,
        "latest_capture_at": latest_capture_at,
        "source_files": [str(path) for path in latest_by_stage.values()],
    }


def _aipl_assets_summary() -> dict[str, Any]:
    files = _latest_user_pdfs("千帆AIPL", "*.pdf")
    if not files:
        return {
            "status": "missing",
            "stages": {},
            "ratios": {},
            "source_files": [],
            "latest_capture_at": None,
        }

    stage_map = {
        "了解": "A",
        "兴趣": "I",
        "新客": "N",
        "老客": "R",
        "亲密": "L",
    }
    stage_metrics: dict[str, dict[str, Any]] = {}
    data_date = None
    latest_capture_at = None
    max_ts = 0.0
    source_files: list[str] = []

    stage_pattern = re.compile(r"(了解|兴趣|新客|老客|亲密)(?:\([A-Z]\))?(\d[\d,]*)(?:年客单\(LTV\)¥?([\d,.]+))?近30日([+-]?\d[\d,]*|-)")
    for path in files:
        text = _extract_pdf_text(path)
        if not text:
            continue
        compact = _normalize_ocr_text(text)
        date_match = re.search(r"数据截[至止]：?(\d{4}-\d{2}-\d{2})", compact)
        if date_match:
            data_date = date_match.group(1)
        found_any = False
        for match in stage_pattern.finditer(compact):
            label_cn = match.group(1)
            stage_code = stage_map[label_cn]
            count = _int_from_token(match.group(2))
            ltv = _float_from_token(match.group(3))
            delta = _int_from_token(match.group(4))
            if count is None:
                continue
            prev = stage_metrics.get(stage_code)
            ts = path.stat().st_mtime
            if prev and float(prev.get("source_ts", 0) or 0) > ts:
                continue
            stage_metrics[stage_code] = {
                "label": label_cn,
                "count": count,
                "delta_30d": delta,
                "ltv": ltv,
                "source_file": str(path),
                "source_ts": ts,
            }
            found_any = True
        if found_any:
            source_files.append(str(path))
        ts = path.stat().st_mtime
        if ts >= max_ts:
            max_ts = ts
            latest_capture_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    for stage_code, label in [("A", "了解"), ("I", "兴趣"), ("N", "新客"), ("R", "老客"), ("L", "亲密")]:
        stage_metrics.setdefault(stage_code, {"label": label, "count": None, "delta_30d": None, "ltv": None, "source_file": None, "source_ts": 0})

    awareness = _float_from_token(stage_metrics["A"]["count"])
    interest = _float_from_token(stage_metrics["I"]["count"])
    new_customer = _float_from_token(stage_metrics["N"]["count"])
    returning = _float_from_token(stage_metrics["R"]["count"])
    loyal = _float_from_token(stage_metrics["L"]["count"])

    ratios = {
        "awareness_to_interest_cvr": (interest / awareness) if awareness else None,
        "interest_to_new_cvr": (new_customer / interest) if interest else None,
        "new_to_returning_cvr": (returning / new_customer) if new_customer else None,
        "returning_to_loyal_cvr": (loyal / returning) if returning else None,
    }

    required_ready = all(stage_metrics.get(code, {}).get("count") is not None for code in ("A", "I", "N", "R"))
    status = "ready" if required_ready else "partial"
    return {
        "status": status,
        "stages": {
            key: {
                "label": stage_metrics[key]["label"],
                "count": stage_metrics[key]["count"],
                "delta_30d": stage_metrics[key]["delta_30d"],
                "ltv": stage_metrics[key]["ltv"],
                "source_file": stage_metrics[key]["source_file"],
            }
            for key in ("A", "I", "N", "R", "L")
        },
        "ratios": ratios,
        "data_date": data_date,
        "latest_capture_at": latest_capture_at,
        "source_files": sorted(set(source_files)),
    }


def _creator_number(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    text = str(value).strip().replace(",", "")
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1]
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    try:
        parsed = float(text) * multiplier
    except ValueError:
        return None
    return parsed / 100.0 if is_percent else parsed


def _normalize_creator_account_panel(home_capture: dict[str, Any] | None) -> dict[str, Any]:
    metrics = (home_capture or {}).get("parsed", {}).get("home_metrics", {})
    return {
        "exposure": _creator_number(metrics.get("曝光数")),
        "views": _creator_number(metrics.get("观看数")),
        "cover_ctr": _creator_number(metrics.get("封面点击率")),
        "completion_rate": _creator_number(metrics.get("视频完播率")),
        "likes": _creator_number(metrics.get("点赞数")),
        "comments": _creator_number(metrics.get("评论数")),
        "saves": _creator_number(metrics.get("收藏数")),
        "shares": _creator_number(metrics.get("分享数")),
        "engagement_actions": sum(
            value or 0.0
            for value in (
                _creator_number(metrics.get("点赞数")),
                _creator_number(metrics.get("评论数")),
                _creator_number(metrics.get("收藏数")),
                _creator_number(metrics.get("分享数")),
            )
        ),
        "net_followers": _creator_number(metrics.get("净涨粉")),
        "new_follows": _creator_number(metrics.get("新增关注")),
        "unfollows": _creator_number(metrics.get("取消关注")),
        "homepage_visitors": _creator_number(metrics.get("主页访客")),
    }


def _normalize_creator_home_export_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    metric_aliases: dict[str, tuple[str, ...]] = {
        "exposure": ("曝光数", "曝光", "曝光量"),
        "views": ("观看数", "观看", "浏览量", "播放量", "阅读量"),
        "cover_ctr": ("封面点击率", "封面点击"),
        "completion_rate": ("视频完播率", "完播率"),
        "likes": ("点赞数", "点赞"),
        "comments": ("评论数", "评论"),
        "saves": ("收藏数", "收藏"),
        "shares": ("分享数", "分享"),
        "net_followers": ("净涨粉", "净增粉"),
        "new_follows": ("新增关注", "新增粉丝"),
        "unfollows": ("取消关注", "取关"),
        "homepage_visitors": ("主页访客", "主页访问"),
    }
    metric_label_aliases = ("指标", "指标名称", "名称", "metric", "name")
    metric_value_aliases = ("数值", "值", "value", "metric_value")

    def _pick(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
        return _creator_export_value(row, aliases)

    panel: dict[str, Any] = {}

    # Format A: two-column metric/value rows.
    for row in rows:
        label = str(_pick(row, metric_label_aliases) or "").strip()
        value = _pick(row, metric_value_aliases)
        if not label:
            continue
        normalized_label = _normalize_creator_header_name(label)
        for target_key, aliases in metric_aliases.items():
            for alias in aliases:
                if _normalize_creator_header_name(alias) == normalized_label:
                    panel[target_key] = _creator_number(value)
                    break

    # Format B: one row with KPI headers as columns.
    if not panel:
        for target_key, aliases in metric_aliases.items():
            panel[target_key] = _creator_number(_pick(rows[0], aliases))

    panel["engagement_actions"] = sum(
        value or 0.0
        for value in (
            panel.get("likes"),
            panel.get("comments"),
            panel.get("saves"),
            panel.get("shares"),
        )
    )
    return panel


def _merge_creator_account_panel(json_panel: dict[str, Any], export_panel: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not json_panel and not export_panel:
        return {}, "missing"
    if json_panel and not export_panel:
        return json_panel, "json"
    if export_panel and not json_panel:
        return export_panel, "export"
    merged = dict(export_panel)
    for key, value in json_panel.items():
        if value not in (None, "", 0, 0.0):
            merged[key] = value
    if "engagement_actions" not in merged or merged["engagement_actions"] in (None, "", 0, 0.0):
        merged["engagement_actions"] = sum(
            value or 0.0
            for value in (
                merged.get("likes"),
                merged.get("comments"),
                merged.get("saves"),
                merged.get("shares"),
            )
        )
    return merged, "hybrid"


def _normalize_creator_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("/", "-").replace(".", "-")
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split(" ")
    if parts:
        date_part = parts[0]
        date_bits = [bit.zfill(2) for bit in date_part.split("-") if bit]
        if len(date_bits) >= 3:
            date_part = "-".join(date_bits[:3])
        parts[0] = date_part
    return " ".join(parts)


def _creator_row_key(row: dict[str, Any]) -> str:
    note_id = str(row.get("note_id") or "").strip()
    if note_id:
        return note_id
    return f"{str(row.get('title') or '').strip()}::{_normalize_creator_date(row.get('published_at'))}"


def _normalize_creator_header_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-:/（）()【】\[\]·,，。]+", "", text)


def _xlsx_col_to_index(ref: str) -> int:
    letters = "".join(ch for ch in ref.upper() if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return max(0, index - 1)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for si in root.findall("x:si", ns):
        parts = [node.text or "" for node in si.findall(".//x:t", ns)]
        strings.append("".join(parts))
    return strings


def _xlsx_first_sheet_path(archive: zipfile.ZipFile) -> str | None:
    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_rel = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheets = workbook.findall("x:sheets/x:sheet", ns_main)
    if not sheets:
        return None
    rel_id = sheets[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if not rel_id:
        return "xl/worksheets/sheet1.xml"
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "")
            return target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
    return "xl/worksheets/sheet1.xml"


def _read_xlsx_rows(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        sheet_path = _xlsx_first_sheet_path(archive)
        if not sheet_path or sheet_path not in archive.namelist():
            return []
        shared_strings = _xlsx_shared_strings(archive)
        root = ET.fromstring(archive.read(sheet_path))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", ns):
        cells: dict[int, str] = {}
        max_index = -1
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            index = _xlsx_col_to_index(ref)
            max_index = max(max_index, index)
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(".//x:t", ns))
            else:
                raw = cell.findtext("x:v", default="", namespaces=ns)
                if cell_type == "s":
                    try:
                        value = shared_strings[int(raw)]
                    except Exception:
                        value = raw
                else:
                    value = raw
            cells[index] = value
        if max_index >= 0:
            rows.append([cells.get(i, "") for i in range(max_index + 1)])
    if not rows:
        return []
    headers = [str(item or "").strip() for item in rows[0]]
    records: list[dict[str, Any]] = []
    for raw_row in rows[1:]:
        if not any(str(item or "").strip() for item in raw_row):
            continue
        row = {}
        for index, header in enumerate(headers):
            header_name = header or f"column_{index + 1}"
            row[header_name] = raw_row[index] if index < len(raw_row) else ""
        records.append(row)
    return records


def _read_delimited_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    sample = text[:2048]
    delimiter = "\t" if "\t" in sample else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    return [row for row in rows if any(str(value or "").strip() for value in row.values())]


def _read_html_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    table_match = re.search(r"<table.*?</table>", text, flags=re.IGNORECASE | re.DOTALL)
    if not table_match:
        return []
    table = table_match.group(0)
    row_blocks = re.findall(r"<tr.*?>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL)
    parsed_rows: list[list[str]] = []
    for block in row_blocks:
        cells = re.findall(r"<t[hd].*?>(.*?)</t[hd]>", block, flags=re.IGNORECASE | re.DOTALL)
        values = [re.sub(r"<.*?>", "", cell).strip() for cell in cells]
        if any(values):
            parsed_rows.append(values)
    if len(parsed_rows) < 2:
        return []
    headers = parsed_rows[0]
    records: list[dict[str, Any]] = []
    for row in parsed_rows[1:]:
        records.append({headers[index] if index < len(headers) else f"column_{index + 1}": value for index, value in enumerate(row)})
    return records


def _read_creator_export_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            if path.read_bytes()[:2] == b"PK":
                return _read_xlsx_rows(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            if "<table" in text.lower():
                return _read_html_rows(path)
            return _read_delimited_rows(path)
        if suffix == ".csv":
            return _read_delimited_rows(path)
    except Exception:
        return []
    return []


def _creator_export_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized_row = {_normalize_creator_header_name(key): value for key, value in row.items()}
    for alias in aliases:
        if _normalize_creator_header_name(alias) in normalized_row:
            return normalized_row[_normalize_creator_header_name(alias)]
    return None


def _normalize_creator_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        title = str(_creator_export_value(row, ("标题", "笔记标题", "作品标题", "内容标题", "title")) or "").strip()
        published_at = _normalize_creator_date(_creator_export_value(row, ("发布时间", "发布时间间", "发布时间/日期", "发布于", "published_at")))
        normalized_date = published_at[:10]
        if normalized_date and normalized_date < LE_FOND_CONTENT_START_DATE:
            continue
        normalized.append(
            {
                "title": title,
                "published_at": published_at,
                "duration": str(_creator_export_value(row, ("时长", "视频时长", "duration")) or ""),
                "views": _creator_number(_creator_export_value(row, ("观看数", "观看", "浏览量", "播放量", "阅读量", "views"))) or 0.0,
                "likes": _creator_number(_creator_export_value(row, ("点赞数", "点赞", "likes"))) or 0.0,
                "saves": _creator_number(_creator_export_value(row, ("收藏数", "收藏", "saves"))) or 0.0,
                "comments": _creator_number(_creator_export_value(row, ("评论数", "评论", "comments"))) or 0.0,
                "shares": _creator_number(_creator_export_value(row, ("分享数", "分享", "shares"))) or 0.0,
                "note_id": str(_creator_export_value(row, ("笔记id", "笔记ID", "作品ID", "note_id")) or "").strip(),
                "type": str(_creator_export_value(row, ("笔记类型", "类型", "type")) or "").strip(),
            }
        )
    return [row for row in normalized if row["title"] or row["note_id"]]


def _merge_creator_rows(json_rows: list[dict[str, Any]], export_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    merged: dict[str, dict[str, Any]] = {}
    sources_seen: set[str] = set()
    for source_name, rows in (("json", json_rows), ("export", export_rows)):
        if rows:
            sources_seen.add(source_name)
        for row in rows:
            key = _creator_row_key(row)
            current = merged.get(key, {}).copy()
            current_sources = set(current.get("row_sources", []))
            for field, value in row.items():
                if field == "row_sources":
                    continue
                if field == "note_id" and current.get("note_id") and not value:
                    continue
                if value not in (None, "", 0, 0.0):
                    current[field] = value
                elif field not in current:
                    current[field] = value
            current_sources.add(source_name)
            current["row_sources"] = sorted(current_sources)
            merged[key] = current
    source_mode = "missing"
    if sources_seen == {"json"}:
        source_mode = "json"
    elif sources_seen == {"export"}:
        source_mode = "export"
    elif sources_seen == {"json", "export"}:
        source_mode = "hybrid"
    rows = list(merged.values())
    rows.sort(key=lambda item: (float(item.get("views", 0) or 0), float(item.get("saves", 0) or 0), float(item.get("comments", 0) or 0)), reverse=True)
    return rows, source_mode


def _normalize_creator_note_inventory(note_capture: dict[str, Any] | None, export_rows: list[dict[str, Any]] | None = None, export_path: Path | None = None) -> dict[str, Any]:
    parsed = (note_capture or {}).get("parsed", {})
    export_rows = export_rows or []
    rows = []
    for row in parsed.get("note_rows", []) or []:
        published_at = str(row.get("published_at") or "")
        normalized_date = _normalize_creator_date(published_at)
        if normalized_date and normalized_date[:10] < LE_FOND_CONTENT_START_DATE:
            continue
        rows.append(
            {
                "title": str(row.get("title") or "").strip(),
                "published_at": published_at,
                "duration": str(row.get("duration") or ""),
                "views": _creator_number(row.get("views")) or 0.0,
                "likes": _creator_number(row.get("likes")) or 0.0,
                "saves": _creator_number(row.get("saves")) or 0.0,
                "comments": _creator_number(row.get("comments")) or 0.0,
                "shares": _creator_number(row.get("shares")) or 0.0,
                "note_id": str(row.get("note_id") or ""),
                "type": str(row.get("type") or ""),
            }
        )
    rows, source_mode = _merge_creator_rows(rows, export_rows)
    json_total_note_count = parsed.get("total_note_count")
    export_total_note_count = len(export_rows) if export_rows else None
    total_note_count = max(
        [value for value in (json_total_note_count, export_total_note_count, len(rows)) if isinstance(value, (int, float))],
        default=len(rows),
    )
    json_page_count = parsed.get("page_count_captured", 1 if rows else 0)
    export_page_count = 1 if export_rows else 0
    page_count_captured = max(int(json_page_count or 0), export_page_count)
    if export_rows:
        truncated = bool(total_note_count and len(rows) < total_note_count)
        expected_page_count = page_count_captured
    else:
        truncated = bool(parsed.get("truncated"))
        expected_page_count = parsed.get("expected_page_count")
    return {
        "rows": rows,
        "total_note_count": int(total_note_count or 0),
        "page_count_captured": page_count_captured,
        "expected_page_count": expected_page_count,
        "truncated": truncated,
        "brand_content_cutoff": LE_FOND_CONTENT_START_DATE,
        "source_mode": source_mode,
        "source_counts": {
            "json_rows": len(parsed.get("note_rows", []) or []),
            "export_rows": len(export_rows),
            "merged_rows": len(rows),
        },
        "source_file": str(export_path) if export_path else None,
    }


def _cn_magnitude(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "").replace("，", "")
    match = re.search(r"(\d+(?:\.\d+)?)([万亿]?)", text)
    if not match:
        return None
    base = float(match.group(1))
    unit = match.group(2)
    if unit == "万":
        base *= 10000.0
    elif unit == "亿":
        base *= 100000000.0
    return base


def _normalize_creator_events(
    event_capture: dict[str, Any] | None,
    export_rows: list[dict[str, Any]] | None = None,
    export_path: Path | None = None,
) -> dict[str, Any]:
    export_rows = export_rows or []
    parsed = (event_capture or {}).get("parsed", {})
    lines = [str(item).strip() for item in (parsed.get("highlights") or []) if str(item).strip()]
    if not lines:
        lines = [line.strip() for line in str((event_capture or {}).get("body_text") or "").splitlines() if line.strip()]
    date_re = re.compile(r"\b(\d{2}-\d{2})\s*至\s*(\d{2}-\d{2})\b")
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = date_re.search(line)
        if not match:
            continue
        title = lines[index - 1] if index > 0 else ""
        if title in {"查看详情", "全部活动", "我的收藏", "排序", "默认排序"}:
            title = ""
        events.append(
            {
                "title": title,
                "date_range": f"{match.group(1)}至{match.group(2)}",
                "start_mmdd": match.group(1),
                "end_mmdd": match.group(2),
            }
        )
    export_titles: list[str] = []
    for row in export_rows:
        title = str(
            _creator_export_value(
                row,
                ("活动名称", "活动标题", "标题", "主题", "name", "title"),
            )
            or ""
        ).strip()
        if title:
            export_titles.append(title)

    source_mode = "missing"
    if events and export_rows:
        source_mode = "hybrid"
    elif events:
        source_mode = "json"
    elif export_rows:
        source_mode = "export"
    now = datetime.now(timezone.utc)
    starts_within_7d = 0
    for event in events:
        start = str(event.get("start_mmdd") or "")
        if not re.match(r"^\d{2}-\d{2}$", start):
            continue
        try:
            start_dt = datetime.fromisoformat(f"{now.year}-{start}T00:00:00+00:00")
            delta = (start_dt - now).days
            if 0 <= delta <= 7:
                starts_within_7d += 1
        except ValueError:
            continue
    return {
        "events": events[:30],
        "active_event_count": len(events),
        "events_start_within_7d": starts_within_7d,
        "top_event_titles": [item.get("title", "") for item in events[:8] if item.get("title")],
        "source_mode": source_mode,
        "source_counts": {
            "json_events": len(events),
            "export_rows": len(export_rows),
            "export_titles": len(export_titles),
        },
        "source_file": str(export_path) if export_path else None,
    }


def _normalize_creator_inspiration(
    inspiration_capture: dict[str, Any] | None,
    export_rows: list[dict[str, Any]] | None = None,
    export_path: Path | None = None,
) -> dict[str, Any]:
    export_rows = export_rows or []
    parsed = (inspiration_capture or {}).get("parsed", {})
    lines = [str(item).strip() for item in (parsed.get("highlights") or []) if str(item).strip()]
    if not lines:
        lines = [line.strip() for line in str((inspiration_capture or {}).get("body_text") or "").splitlines() if line.strip()]
    stat_re = re.compile(r"(?P<participants>[\d\.]+[万亿]?)人参与\s*[·•]\s*(?P<views>[\d\.]+[万亿]?)次浏览")
    topics: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = stat_re.search(line)
        if not match:
            continue
        topic_name = lines[index - 1] if index > 0 else ""
        participants = _cn_magnitude(match.group("participants")) or 0.0
        views = _cn_magnitude(match.group("views")) or 0.0
        topics.append(
            {
                "topic": topic_name,
                "participants": participants,
                "views": views,
                "raw_stats": line,
            }
        )

    for row in export_rows:
        topic_name = str(_creator_export_value(row, ("话题", "选题", "主题", "topic", "title", "名称")) or "").strip()
        participants = _cn_magnitude(str(_creator_export_value(row, ("参与人数", "参与", "参与量", "participants")) or ""))
        views = _cn_magnitude(str(_creator_export_value(row, ("浏览量", "浏览", "观看", "views")) or ""))
        if topic_name and (participants is not None or views is not None):
            topics.append(
                {
                    "topic": topic_name,
                    "participants": float(participants or 0.0),
                    "views": float(views or 0.0),
                    "raw_stats": "export",
                }
            )

    deduped: dict[str, dict[str, Any]] = {}
    for item in topics:
        key = str(item.get("topic") or "").strip().lower() or str(item.get("raw_stats") or "")
        current = deduped.get(key)
        if current is None or float(item.get("views", 0) or 0) >= float(current.get("views", 0) or 0):
            deduped[key] = item
    ranked_topics = sorted(
        deduped.values(),
        key=lambda item: (float(item.get("views", 0) or 0), float(item.get("participants", 0) or 0)),
        reverse=True,
    )
    high_heat_count = sum(
        1
        for item in ranked_topics
        if float(item.get("views", 0) or 0) >= 100000000.0 or float(item.get("participants", 0) or 0) >= 100000.0
    )
    source_mode = "missing"
    if parsed.get("highlights") and export_rows:
        source_mode = "hybrid"
    elif parsed.get("highlights"):
        source_mode = "json"
    elif export_rows:
        source_mode = "export"
    return {
        "topics": ranked_topics[:40],
        "topic_count": len(ranked_topics),
        "high_heat_topic_count": high_heat_count,
        "top_topics": [item.get("topic", "") for item in ranked_topics[:8] if item.get("topic")],
        "source_mode": source_mode,
        "source_counts": {
            "json_highlights": len(parsed.get("highlights", []) or []),
            "export_rows": len(export_rows),
            "topics": len(ranked_topics),
        },
        "source_file": str(export_path) if export_path else None,
    }


def _creator_platform_summary() -> dict[str, Any]:
    home_capture = latest_creator_capture("creator_home")
    note_capture = latest_creator_capture("creator_note_manager")
    events_capture = latest_creator_capture("creator_events")
    inspiration_capture = latest_creator_capture("creator_inspiration")
    home_export_path = latest_creator_export("creator_home")
    note_export_path = latest_creator_export("creator_note_manager")
    events_export_path = latest_creator_export("creator_events")
    inspiration_export_path = latest_creator_export("creator_inspiration")
    home_export_rows = _read_creator_export_rows(home_export_path)
    note_export_rows = _normalize_creator_export_rows(_read_creator_export_rows(note_export_path))
    events_export_rows = _read_creator_export_rows(events_export_path)
    inspiration_export_rows = _read_creator_export_rows(inspiration_export_path)
    account_panel, account_panel_mode = _merge_creator_account_panel(
        _normalize_creator_account_panel(home_capture),
        _normalize_creator_home_export_metrics(home_export_rows),
    )
    note_inventory = _normalize_creator_note_inventory(note_capture, note_export_rows, note_export_path)
    events_board = _normalize_creator_events(events_capture, events_export_rows, events_export_path)
    inspiration_board = _normalize_creator_inspiration(inspiration_capture, inspiration_export_rows, inspiration_export_path)
    home_visual = ((home_capture or {}).get("parsed", {}) or {}).get("visual_signals", {})
    note_visual = ((note_capture or {}).get("parsed", {}) or {}).get("visual_signals", {})
    events_visual = ((events_capture or {}).get("parsed", {}) or {}).get("visual_signals", {})
    inspiration_visual = ((inspiration_capture or {}).get("parsed", {}) or {}).get("visual_signals", {})
    freshness = {
        "creator_home_days": _days_since((home_capture or {}).get("captured_at")),
        "creator_home_export_days": _days_since(datetime.fromtimestamp(home_export_path.stat().st_mtime, tz=timezone.utc).isoformat() if home_export_path and home_export_path.exists() else None),
        "creator_note_manager_days": _days_since((note_capture or {}).get("captured_at")),
        "creator_note_export_days": _days_since(datetime.fromtimestamp(note_export_path.stat().st_mtime, tz=timezone.utc).isoformat() if note_export_path and note_export_path.exists() else None),
        "creator_events_days": _days_since((events_capture or {}).get("captured_at")),
        "creator_events_export_days": _days_since(datetime.fromtimestamp(events_export_path.stat().st_mtime, tz=timezone.utc).isoformat() if events_export_path and events_export_path.exists() else None),
        "creator_inspiration_days": _days_since((inspiration_capture or {}).get("captured_at")),
        "creator_inspiration_export_days": _days_since(datetime.fromtimestamp(inspiration_export_path.stat().st_mtime, tz=timezone.utc).isoformat() if inspiration_export_path and inspiration_export_path.exists() else None),
    }
    return {
        "source_root": str(CREATOR_AUTO_ROOT),
        "home_capture": home_capture,
        "home_export": {
            "path": str(home_export_path) if home_export_path else None,
            "row_count": len(home_export_rows),
        },
        "note_manager_capture": note_capture,
        "note_manager_export": {
            "path": str(note_export_path) if note_export_path else None,
            "row_count": len(note_export_rows),
        },
        "events_capture": events_capture,
        "events_export": {
            "path": str(events_export_path) if events_export_path else None,
            "row_count": len(events_export_rows),
        },
        "inspiration_capture": inspiration_capture,
        "inspiration_export": {
            "path": str(inspiration_export_path) if inspiration_export_path else None,
            "row_count": len(inspiration_export_rows),
        },
        "creator_account_panel": account_panel,
        "creator_note_inventory": note_inventory,
        "creator_events_board": events_board,
        "creator_inspiration_board": inspiration_board,
        "visual_signals": {
            "creator_home": home_visual,
            "creator_note_manager": note_visual,
            "creator_events": events_visual,
            "creator_inspiration": inspiration_visual,
        },
        "freshness": freshness,
        "source_precedence": {
            "commerce_truth": "qianfan",
            "creator_freshness_content_truth": "creator_platform",
            "historical_content_truth": "posts_enriched",
            "creator_note_inventory_mode": note_inventory.get("source_mode", "missing"),
            "creator_account_panel_mode": account_panel_mode,
            "creator_events_mode": events_board.get("source_mode", "missing"),
            "creator_inspiration_mode": inspiration_board.get("source_mode", "missing"),
        },
        "capture_metadata": {
            "creator_home_captured_at": (home_capture or {}).get("captured_at"),
            "creator_home_export_path": str(home_export_path) if home_export_path else None,
            "creator_home_export_rows": len(home_export_rows),
            "creator_note_manager_captured_at": (note_capture or {}).get("captured_at"),
            "creator_note_manager_page_count_captured": note_inventory.get("page_count_captured", 0),
            "creator_note_manager_truncated": note_inventory.get("truncated", False),
            "creator_note_manager_export_path": str(note_export_path) if note_export_path else None,
            "creator_note_manager_export_rows": len(note_export_rows),
            "creator_home_chart_nodes": int(home_visual.get("chart_node_count", 0) or 0),
            "creator_home_numeric_samples": len(home_visual.get("numeric_text_samples", []) or []),
            "creator_note_manager_chart_nodes": int(note_visual.get("chart_node_count", 0) or 0),
            "creator_note_manager_numeric_samples": len(note_visual.get("numeric_text_samples", []) or []),
            "creator_events_captured_at": (events_capture or {}).get("captured_at"),
            "creator_events_export_path": str(events_export_path) if events_export_path else None,
            "creator_events_export_rows": len(events_export_rows),
            "creator_events_active_count": events_board.get("active_event_count", 0),
            "creator_events_chart_nodes": int(events_visual.get("chart_node_count", 0) or 0),
            "creator_events_numeric_samples": len(events_visual.get("numeric_text_samples", []) or []),
            "creator_inspiration_captured_at": (inspiration_capture or {}).get("captured_at"),
            "creator_inspiration_export_path": str(inspiration_export_path) if inspiration_export_path else None,
            "creator_inspiration_export_rows": len(inspiration_export_rows),
            "creator_inspiration_topic_count": inspiration_board.get("topic_count", 0),
            "creator_inspiration_chart_nodes": int(inspiration_visual.get("chart_node_count", 0) or 0),
            "creator_inspiration_numeric_samples": len(inspiration_visual.get("numeric_text_samples", []) or []),
        },
    }


def _latest_surface_exports(subdir: str, sample_limit: int = 3) -> dict[str, Any]:
    files = [path for path in latest_files(subdir) if path.is_file()]
    if not files:
        return {
            "subdir": subdir,
            "row_count": 0,
            "file_count": 0,
            "latest_file": None,
            "latest_capture_at": None,
            "sample_rows": [],
        }
    files.sort(key=lambda path: (path.stat().st_mtime, path.name))
    latest_file = files[-1]
    rows = _read_creator_export_rows(latest_file)
    return {
        "subdir": subdir,
        "row_count": len(rows),
        "file_count": len(files),
        "latest_file": str(latest_file),
        "latest_capture_at": datetime.fromtimestamp(latest_file.stat().st_mtime, tz=timezone.utc).isoformat(),
        "sample_rows": rows[:sample_limit],
    }


def _ops_domain_payload(domain_name: str, surfaces: dict[str, str]) -> dict[str, Any]:
    surface_rows: dict[str, Any] = {}
    total_rows = 0
    available_surfaces = 0
    latest_capture_at = None
    latest_capture_ts = 0.0
    for surface_name, subdir in surfaces.items():
        payload = _latest_surface_exports(subdir)
        surface_rows[surface_name] = payload
        total_rows += int(payload.get("row_count", 0) or 0)
        if int(payload.get("row_count", 0) or 0) > 0:
            available_surfaces += 1
        latest_file = payload.get("latest_file")
        if latest_file:
            ts = Path(latest_file).stat().st_mtime
            if ts >= latest_capture_ts:
                latest_capture_ts = ts
                latest_capture_at = payload.get("latest_capture_at")
    status = "missing"
    if available_surfaces == len(surfaces) and len(surfaces) > 0:
        status = "ready"
    elif available_surfaces > 0:
        status = "partial"
    return {
        "domain": domain_name,
        "status": status,
        "total_rows": total_rows,
        "available_surfaces": available_surfaces,
        "total_surfaces": len(surfaces),
        "latest_capture_at": latest_capture_at,
        "surfaces": surface_rows,
    }


def _reconcile_report(extracted: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    parser_mode = "raw_cache_fallback"
    monthly_rows = len(extracted.get("monthly_kpi", []))
    try:
        business_full = business_full_view()
        raw_rows = len(business_full.get("buyer_type", []))
        checks.append({
            "name": "monthly_business_health_row_count",
            "extracted_rows": monthly_rows,
            "raw_rows": raw_rows,
            "status": "pass" if monthly_rows > 0 and raw_rows > 0 else "warning",
            "parser_mode": "business_full_cache",
        })
    except RawSourceUnavailable as exc:
        parser_mode = "degraded_no_legacy_cache"
        checks.append({
            "name": "monthly_business_health_row_count",
            "extracted_rows": monthly_rows,
            "raw_rows": None,
            "status": "warning",
            "parser_mode": "none",
            "reason": "legacy_raw_cache_missing",
            "error": str(exc),
        })

    try:
        funnel_sample = sheet_sample("店铺页/店铺页转化漏斗")
        checks.append({
            "name": "shop_funnel_row_count",
            "extracted_rows": len(extracted.get("shop_funnel", [])),
            "raw_rows": funnel_sample.get("rows"),
            "status": "pass" if abs(len(extracted.get("shop_funnel", [])) - int(funnel_sample.get("rows", 0) or 0)) <= 1 else "warning",
            "parser_mode": funnel_sample.get("parser_mode"),
            "source": funnel_sample.get("cache_key"),
        })
    except RawSourceUnavailable as exc:
        parser_mode = "degraded_no_legacy_cache"
        checks.append({
            "name": "shop_funnel_row_count",
            "extracted_rows": len(extracted.get("shop_funnel", [])),
            "raw_rows": None,
            "status": "warning",
            "parser_mode": "none",
            "reason": "legacy_raw_cache_missing",
            "error": str(exc),
        })

    try:
        month_sample = sheet_sample("商家经营汇总/商家经营核心数据汇总(2026年03月)")
        headers = month_sample.get("sample", [[], []])[0] if month_sample.get("sample") else []
        checks.append({
            "name": "monthly_kpi_latest_headers_present",
            "expected_headers": headers,
            "status": "pass" if month_sample.get("sample") else "warning",
            "parser_mode": month_sample.get("parser_mode"),
            "source": month_sample.get("cache_key"),
        })
    except RawSourceUnavailable as exc:
        parser_mode = "degraded_no_legacy_cache"
        checks.append({
            "name": "monthly_kpi_latest_headers_present",
            "expected_headers": [],
            "status": "warning",
            "parser_mode": "none",
            "reason": "legacy_raw_cache_missing",
            "error": str(exc),
        })

    warnings = [check for check in checks if check["status"] != "pass"]
    return {
        "parser_mode": parser_mode,
        "checks": checks,
        "warning_count": len(warnings),
        "status": "pass" if not warnings else "warning",
    }


def build_first_party(snapshot_id: str) -> dict[str, Any]:
    payload, missing, source_files = _load_bundle(FIRST_PARTY_FILES)
    creator_platform = _creator_platform_summary()
    deal_population_flow = _deal_population_flow_summary()
    aipl_assets = _aipl_assets_summary()
    service_after_sale = _ops_domain_payload(
        "service_after_sale",
        {
            "customer_data": "客服数据",
            "after_sale_data": "售后数据",
            "aftersale_manage": "售后管理",
            "reviews": "评价",
        },
    )
    fulfillment_logistics = _ops_domain_payload(
        "fulfillment_logistics",
        {
            "logistics_data": "物流数据",
            "dispatching_center": "发货中心",
        },
    )
    settlement_ops = _ops_domain_payload(
        "settlement_ops",
        {
            "order_query": "订单查询",
            "settlement_funds": "货款资金",
            "pending_settle_orders": "待结算订单",
            "deposit_category_base": "保证金明细",
            "shelf_goods": "售卖中商品",
        },
    )
    normalized = {
        "snapshot_id": snapshot_id,
        "parser_mode": "extracted_seed",
        "source_files": source_files,
        "missing_sources": missing,
        "monthly_business_health": {
            "rows": payload.get("monthly_kpi", []),
            "latest": _latest_month(payload.get("monthly_kpi", [])),
            "months": [row.get("_month") for row in payload.get("monthly_kpi", [])],
        },
        "shop_funnel": {
            "rows": payload.get("shop_funnel", []),
        },
        "search_terms": _search_summary(payload.get("search_terms", [])),
        "sku_performance": {
            "rows": payload.get("sku_performance", []),
        },
        "refund_risk": _refund_summary(payload.get("refund_analysis", [])),
        "channel_performance": _channel_summary(payload.get("channel_performance", [])),
        "user_portrait": payload.get("user_portrait", {}),
        "content_performance": _content_summary(payload.get("posts_enriched", {})),
        "visual_product_features": payload.get("visual_features_products", []),
        "creator_platform": creator_platform,
        "user_asset_signals": {
            "deal_population_flow": deal_population_flow,
            "aipl_assets": aipl_assets,
        },
        "service_after_sale": service_after_sale,
        "fulfillment_logistics": fulfillment_logistics,
        "settlement_ops": settlement_ops,
        "source_precedence": {
            "commerce_truth": "qianfan",
            "creator_freshness_content_truth": "creator_platform",
            "historical_content_truth": "posts_enriched",
        },
        "reconcile": _reconcile_report(payload),
    }
    path = object_path("normalized_first_party", snapshot_id)
    write_json(path, normalized)
    write_json(ARTIFACT_DIRS["reconcile_report"] / f"{snapshot_id}.json", normalized["reconcile"])
    return normalized


def build_benchmark(snapshot_id: str) -> dict[str, Any]:
    payload, missing, source_files = _load_bundle(BENCHMARK_FILES)
    per_sku_dir = KNOWLEDGE_PERSKU_ROOT
    per_sku = []
    for path in sorted(per_sku_dir.glob("*")):
        if not path.is_dir():
            continue
        per_sku.append(
            {
                "path": str(path),
                "name": path.name,
                "files": sorted(child.name for child in path.glob("*.json")),
                "mtime": int(path.stat().st_mtime),
            }
        )
    payload_out = {
        "snapshot_id": snapshot_id,
        "parser_mode": "benchmark_seed",
        "source_files": source_files,
        "missing_sources": missing,
        "competitor_benchmarks": payload.get("competitor_benchmarks", {}),
        "per_sku_corpus": per_sku,
    }
    path = object_path("normalized_benchmark", snapshot_id)
    write_json(path, payload_out)
    return payload_out
