"""
xlsx_etl.py — XLSX → metrics_snapshot JSON

从千帆导出的 XLSX 文件中提取结构化指标，
输出标准 metrics_snapshot 供 Opus 分析使用。

依赖：
  - revenue_os.ingest.extracted._read_xlsx_rows(path) — XLSX 解析
  - revenue_os.foundation.config.RAW_SOURCE_AUTO_ROOT — 数据目录
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from revenue_os.foundation.config import RAW_SOURCE_AUTO_ROOT
from revenue_os.ingest.extracted import _read_xlsx_rows


# ── 工具函数 ───────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    """从各种格式中提取 float（支持百分号、逗号、万）"""
    if value is None or str(value).strip() in ("", "-", "--", "N/A"):
        return default
    text = str(value).strip().replace(",", "").replace("，", "").replace(" ", "")
    is_pct = text.endswith("%")
    if is_pct:
        text = text[:-1]
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    try:
        result = float(text) * multiplier
        return result / 100.0 if is_pct else result
    except ValueError:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))


def _find_files(data_dir: Path, patterns: list[str]) -> list[Path]:
    """在目录中查找匹配模式的文件（递归，按修改时间排序）"""
    found: list[Path] = []
    for pattern in patterns:
        found.extend(data_dir.rglob(pattern))
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def _pick_column(row: dict[str, Any], *aliases: str) -> Any:
    """尝试多个列名别名，返回第一个匹配的值"""
    for alias in aliases:
        if alias in row:
            return row[alias]
        # 模糊匹配：去掉空格和括号
        normalized = alias.replace(" ", "").replace("（", "(").replace("）", ")")
        for key, value in row.items():
            if key.replace(" ", "").replace("（", "(").replace("）", ")") == normalized:
                return value
    return None


# ── 解析器 ─────────────────────────────────────────────────────────────────

def parse_transaction_overview(xlsx_paths: list[Path]) -> dict[str, Any]:
    """解析商家成交数据概览，提取 GMV/订单/转化率/客单价"""
    monthly_data: list[dict[str, Any]] = []

    for path in xlsx_paths:
        rows = _read_xlsx_rows(path)
        for row in rows:
            month_label = str(
                _pick_column(row, "月份", "时间", "日期", "month", "统计月份") or ""
            ).strip()

            gmv = _safe_float(_pick_column(
                row, "成交金额", "支付金额", "GMV", "成交额", "销售额"
            ))
            orders = _safe_int(_pick_column(
                row, "成交订单数", "订单数", "支付订单数", "订单量"
            ))
            visitors = _safe_int(_pick_column(
                row, "店铺访客数", "访客数", "UV", "进店人数"
            ))
            cvr = _safe_float(_pick_column(
                row, "支付转化率", "转化率", "进店-支付转化率", "店铺转化率"
            ))
            aov = _safe_float(_pick_column(
                row, "客单价", "AOV", "笔单价"
            ))

            if gmv > 0 or orders > 0:
                # 计算缺失的衍生值
                if aov == 0 and orders > 0:
                    aov = gmv / orders
                if cvr == 0 and visitors > 0 and orders > 0:
                    cvr = orders / visitors

                monthly_data.append({
                    "month": month_label,
                    "gmv": round(gmv, 2),
                    "orders": orders,
                    "visitors": visitors,
                    "cvr": round(cvr, 4),
                    "aov": round(aov, 2),
                    "source_file": str(path),
                })

    # 取最新月数据作为 latest
    latest = monthly_data[-1] if monthly_data else {}
    return {
        "monthly": monthly_data,
        "latest": latest,
        "month_count": len(monthly_data),
    }


def parse_ainrl_funnel(json_paths: list[Path]) -> dict[str, Any]:
    """解析 AINRL 用户漏斗 JSON（或 XLSX）"""
    stages: dict[str, int] = {"a": 0, "i": 0, "n": 0, "r": 0, "l": 0}
    stage_map = {
        "了解": "a", "A": "a", "awareness": "a",
        "兴趣": "i", "I": "i", "interest": "i",
        "新客": "n", "N": "n", "new": "n",
        "老客": "r", "R": "r", "returning": "r",
        "亲密": "l", "L": "l", "loyal": "l",
    }

    for path in json_paths:
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                # 支持多种 JSON 格式
                if isinstance(data, dict):
                    for key, mapped in stage_map.items():
                        if key in data:
                            stages[mapped] = max(stages[mapped], _safe_int(data[key]))
                elif isinstance(data, list):
                    for item in data:
                        label = str(item.get("stage", item.get("阶段", ""))).strip()
                        count = _safe_int(item.get("count", item.get("人数", 0)))
                        mapped = stage_map.get(label)
                        if mapped:
                            stages[mapped] = max(stages[mapped], count)
            else:
                rows = _read_xlsx_rows(path)
                for row in rows:
                    label = str(_pick_column(row, "阶段", "stage", "人群") or "").strip()
                    count = _safe_int(_pick_column(row, "人数", "count", "数量"))
                    mapped = stage_map.get(label)
                    if mapped:
                        stages[mapped] = max(stages[mapped], count)
        except Exception:
            continue

    # 计算衍生转化率
    derived: dict[str, float | None] = {}
    derived["a_to_i"] = round(stages["i"] / stages["a"], 4) if stages["a"] > 0 else None
    derived["i_to_n"] = round(stages["n"] / stages["i"], 4) if stages["i"] > 0 else None
    derived["n_to_r"] = round(stages["r"] / stages["n"], 4) if stages["n"] > 0 else None
    derived["r_to_l"] = round(stages["l"] / stages["r"], 4) if stages["r"] > 0 else None

    return {
        **stages,
        "derived": derived,
    }


def parse_refund_analysis(xlsx_paths: list[Path]) -> dict[str, Any]:
    """解析退款分析，计算退款率"""
    monthly_refunds: list[dict[str, Any]] = []

    for path in xlsx_paths:
        rows = _read_xlsx_rows(path)
        for row in rows:
            month = str(_pick_column(row, "月份", "时间", "日期") or "").strip()
            refund_amount = _safe_float(_pick_column(
                row, "退款金额", "退款额", "退款成功金额"
            ))
            refund_orders = _safe_int(_pick_column(
                row, "退款订单数", "退款单数", "退款笔数"
            ))
            refund_rate = _safe_float(_pick_column(
                row, "退款率", "退款率（支付时间）", "退款率(支付时间)"
            ))
            total_orders = _safe_int(_pick_column(
                row, "支付订单数", "总订单数", "订单数"
            ))

            if refund_rate == 0 and total_orders > 0 and refund_orders > 0:
                refund_rate = round(refund_orders / total_orders, 4)

            if refund_amount > 0 or refund_orders > 0 or refund_rate > 0:
                monthly_refunds.append({
                    "month": month,
                    "refund_amount": round(refund_amount, 2),
                    "refund_orders": refund_orders,
                    "refund_rate": round(refund_rate, 4),
                    "source_file": str(path),
                })

    latest = monthly_refunds[-1] if monthly_refunds else {}
    return {
        "monthly": monthly_refunds,
        "latest": latest,
        "latest_refund_rate": latest.get("refund_rate", 0),
    }


def parse_search_terms(xlsx_paths: list[Path]) -> list[dict[str, Any]]:
    """解析搜索词数据，返回 top-10"""
    all_terms: list[dict[str, Any]] = []

    for path in xlsx_paths:
        rows = _read_xlsx_rows(path)
        for row in rows:
            term = str(_pick_column(
                row, "搜索词", "关键词", "搜索关键词", "term", "keyword"
            ) or "").strip()
            if not term:
                continue

            clicks = _safe_int(_pick_column(row, "点击量", "点击次数", "点击数", "clicks"))
            ctr = _safe_float(_pick_column(row, "点击率", "CTR", "ctr"))
            revenue = _safe_float(_pick_column(
                row, "成交金额", "搜索成交金额", "GMV", "revenue"
            ))
            cvr = _safe_float(_pick_column(
                row, "成交转化率", "购买转化率", "转化率", "purchase_cvr"
            ))

            all_terms.append({
                "term": term,
                "clicks": clicks,
                "ctr": round(ctr, 4),
                "revenue": round(revenue, 2),
                "purchase_cvr": round(cvr, 4),
                "source_file": str(path),
            })

    # 按成交金额降序排列，取 top 10
    all_terms.sort(key=lambda t: (t["revenue"], t["clicks"]), reverse=True)
    return all_terms[:10]


def infer_stage(monthly_gmv: float, monthly_orders: int = 0) -> str:
    """根据月GMV和订单量推断经营阶段"""
    if monthly_gmv < 3000 or monthly_orders < 10:
        return "cold_start"
    elif monthly_gmv < 30000:
        return "ramp_up"
    elif monthly_gmv < 100000:
        return "breakthrough"
    else:
        return "daily_ops"


# ── 主入口 ─────────────────────────────────────────────────────────────────

def run_etl(data_dir: Path | None = None) -> dict[str, Any]:
    """
    主入口：扫描 data_dir 下所有文件，返回完整 metrics_snapshot。

    Parameters:
        data_dir: 数据目录，默认 RAW_SOURCE_AUTO_ROOT

    Returns:
        dict: 标准 metrics_snapshot JSON
    """
    if data_dir is None:
        data_dir = RAW_SOURCE_AUTO_ROOT

    if not data_dir.exists():
        return {
            "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "stage": "cold_start",
            "metrics": {},
            "ainrl": {},
            "top_search_terms": [],
            "data_quality": {"sources_found": 0, "sources_expected": 4, "error": "data_dir_not_found"},
        }

    # 查找文件
    transaction_files = _find_files(data_dir, ["*成交*概览*.xlsx", "*成交*数据*.xlsx", "*商家*经营*.xlsx"])
    ainrl_files = _find_files(data_dir, ["*AINRL*.json", "*ainrl*.json", "*漏斗*.json", "*AINRL*.xlsx", "*漏斗*.xlsx", "*人群*.xlsx"])
    refund_files = _find_files(data_dir, ["*退款*.xlsx", "*refund*.xlsx"])
    search_files = _find_files(data_dir, ["*搜索词*.xlsx", "*搜索*总览*.xlsx", "*search*.xlsx"])

    sources_found = sum(1 for files in [transaction_files, ainrl_files, refund_files, search_files] if files)

    # 解析
    transaction = parse_transaction_overview(transaction_files)
    ainrl = parse_ainrl_funnel(ainrl_files)
    refund = parse_refund_analysis(refund_files)
    search_terms = parse_search_terms(search_files)

    # 组装 metrics
    latest_tx = transaction.get("latest", {})
    monthly_gmv = latest_tx.get("gmv", 0)
    monthly_orders = latest_tx.get("orders", 0)
    stage = infer_stage(monthly_gmv, monthly_orders)

    snapshot = {
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "stage": stage,
        "metrics": {
            "monthly_gmv": latest_tx.get("gmv", 0),
            "monthly_orders": monthly_orders,
            "aov": latest_tx.get("aov", 0),
            "shop_visit_to_pay_cvr": latest_tx.get("cvr", 0),
            "visitors": latest_tx.get("visitors", 0),
            "refund_rate": refund.get("latest_refund_rate", 0),
        },
        "ainrl": {
            "a": ainrl.get("a", 0),
            "i": ainrl.get("i", 0),
            "n": ainrl.get("n", 0),
            "r": ainrl.get("r", 0),
            "l": ainrl.get("l", 0),
            "derived": ainrl.get("derived", {}),
        },
        "transaction_history": transaction.get("monthly", []),
        "refund_history": refund.get("monthly", []),
        "top_search_terms": search_terms,
        "data_quality": {
            "sources_found": sources_found,
            "sources_expected": 4,
            "transaction_files": len(transaction_files),
            "ainrl_files": len(ainrl_files),
            "refund_files": len(refund_files),
            "search_files": len(search_files),
        },
    }

    return snapshot


# ── CLI 入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run_etl(data_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
