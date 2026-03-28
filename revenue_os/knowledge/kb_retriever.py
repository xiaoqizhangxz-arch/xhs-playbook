"""
kb_retriever.py — BM25 + SemanticBooster 四维权重检索
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from revenue_os.retrieval.semantic_booster import compute_boost

_REVOS_ROOT  = Path(__file__).resolve().parents[2]
_INDEX_DIR   = _REVOS_ROOT / "knowledge_base" / "indices"
_MERGED_FILE = _REVOS_ROOT / "knowledge_base" / "canonical" / "_merged_all.json"

MISSION_QUERY_MAP: dict[str, tuple[str, str | None]] = {
    "conversion_repair":       ("商品页转化 蓝链 挂链 客服 私信 进店转化", "conversion_path"),
    "aov_lift":                ("客单价 AOV 搭配 组合 定价 锚点", "product_strategy"),
    "repurchase_activation":   ("复购 回购 私域 群聊 老客 生命周期", "account_operation"),
    "search_positioning":      ("搜索词 关键词 SEO 搜索直投 买词 搜索流量", "traffic_acquisition"),
    "content_formula_scaling": ("爆款 封面 标题 公式 视频 内容种草", "content_creation"),
    "data_repair":             ("数据质量 指标 基准 准确率", "data_analytics"),
    "audit_only":              ("平台规则 违禁词 合规 限流", "platform_rules"),
}


def _tokenize(query: str) -> dict[str, float]:
    tokens: dict[str, float] = {}
    for w in re.findall(r"[A-Za-z0-9]{2,}", query.lower()):
        tokens[w] = tokens.get(w, 0) + 3.0
    for n, weight in [(4, 3.0), (3, 2.5), (2, 1.5)]:
        for i in range(len(query) - n + 1):
            gram = query[i: i + n]
            if re.search(r"[\u4e00-\u9fff]", gram):
                tokens[gram] = max(tokens.get(gram, 0), weight)
    return tokens


def _load_index() -> tuple[dict, dict, list]:
    idf      = json.loads((_INDEX_DIR / "idf_index.json").read_text(encoding="utf-8"))
    inverted = json.loads((_INDEX_DIR / "inverted_index.json").read_text(encoding="utf-8"))
    merged   = json.loads(_MERGED_FILE.read_text(encoding="utf-8"))
    all_kos  = [ko for kos in merged.values() for ko in kos]
    return idf, inverted, all_kos


def retrieve_for_mission(
    mission_type: str,
    bottleneck: str | None = None,
    user_state: dict[str, Any] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    BM25 检索 + SemanticBooster（当 user_state 提供时启用）。
    无索引时静默返回空列表，不影响上层流程。
    """
    if not _INDEX_DIR.exists() or not _MERGED_FILE.exists():
        return []
    try:
        idf, inverted, all_kos = _load_index()
    except Exception:
        return []

    query_text, preferred_dim = MISSION_QUERY_MAP.get(
        mission_type, (bottleneck or mission_type, None)
    )
    if bottleneck and bottleneck not in query_text:
        query_text = f"{query_text} {bottleneck}"

    query_tokens = _tokenize(query_text)
    bm25_scores: dict[int, float] = defaultdict(float)

    for tok, tok_weight in query_tokens.items():
        if tok in inverted:
            idf_val = idf.get(tok, 0)
            for idx in inverted[tok]:
                ko = all_kos[idx]
                dim_bonus = 1.5 if preferred_dim and ko.get("dimension") == preferred_dim else 1.0
                bm25_scores[idx] += idf_val * tok_weight * dim_bonus

    # SemanticBooster
    bottleneck_metric = bottleneck if user_state else None
    results = []
    for idx, bm25 in sorted(bm25_scores.items(), key=lambda x: -x[1]):
        ko = all_kos[idx]
        boost = compute_boost(ko, user_state, bottleneck_metric) if user_state else 1.0
        final_score = bm25 * boost
        results.append((idx, final_score, ko))

    results.sort(key=lambda x: -x[1])

    output = []
    for _, score, ko in results[:top_k]:
        output.append({
            "type": "kb_insight",
            "score": round(score, 1),
            "insight": ko.get("insight", ""),
            "detail": ko.get("detail", ""),
            "quotation": str(ko.get("quotation", ""))[:120] if ko.get("quotation") else "",
            "dimension": ko.get("dimension", ""),
            "source_title": ko.get("_session_title", ""),
            "industry": ko.get("_industry") or ko.get("applicable_industry") or [],
            "confidence": ko.get("confidence", ""),
            "triggering_metrics": ko.get("triggering_metrics") or [],
            "stage": ko.get("stage") or [],
        })
    return output
