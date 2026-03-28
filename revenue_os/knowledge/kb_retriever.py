"""
kb_retriever.py — KB → Execution 接入层
将 mission_type + bottleneck 映射到 KB 检索，返回 top-N KO 作为 brief_block 注入 execution package
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

# KB 路径（相对于 Revenue OS 根目录）
_REVOS_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _REVOS_ROOT / "knowledge_base/indices"
_MERGED_FILE = _REVOS_ROOT / "knowledge_base/canonical/_merged_by_dimension.json"

# Mission → (查询词, 优先维度)
MISSION_QUERY_MAP: dict[str, tuple[str, str | None]] = {
    "conversion_repair":       ("商品页转化 蓝链 挂链 客服 私信 进店转化", "conversion_path"),
    "aov_lift":                ("客单价 AOV 搭配 组合 定价 锚点", "product_strategy"),
    "repurchase_activation":   ("复购 回购 私域 群聊 老客 生命周期", "account_operation"),
    "search_positioning":      ("搜索词 关键词 SEO 搜索直投 买词 搜索流量", "traffic_acquisition"),
    "content_formula_scaling": ("爆款 封面 标题 公式 视频 内容种草", "content_creation"),
    "data_repair":             ("数据质量 指标 基准 准确率", "data_analytics"),
    "audit_only":              ("平台规则 违禁词 合规 限流", "platform_rules"),
}

# Le Fond 行业权重（通用/时尚/奢品优先，强无关降权）
_IND_WEIGHTS: dict[str, float] = {
    "通用": 1.5, "服饰": 1.4, "服饰潮流": 1.4, "潮流服饰": 1.4,
    "奢品": 1.4, "珠宝腕表": 1.4, "文玩玉翠": 1.3,
    "美妆": 1.2, "个护": 1.2, "婚嫁": 1.2, "生活服务": 1.1,
    "母婴": 0.6, "汽车": 0.6, "3C家电": 0.6, "乳制品": 0.6, "宠物": 0.7,
}


def _ind_weight(ko: dict[str, Any]) -> float:
    inds = ko.get("_industry", [])
    return max((_IND_WEIGHTS.get(i, 1.0) for i in inds), default=1.0)


def _tokenize(query: str) -> dict[str, float]:
    tokens: dict[str, float] = {}
    for w in re.findall(r"[A-Za-z0-9]{2,}", query.lower()):
        tokens[w] = tokens.get(w, 0) + 3.0
    for n, weight in [(4, 3.0), (3, 2.5), (2, 1.5)]:
        for i in range(len(query) - n + 1):
            gram = query[i : i + n]
            if re.search(r"[\u4e00-\u9fff]", gram):
                tokens[gram] = max(tokens.get(gram, 0), weight)
    return tokens


def _load_index() -> tuple[dict, dict, list]:
    idf = json.loads((_INDEX_DIR / "idf_index.json").read_text(encoding="utf-8"))
    inverted = json.loads((_INDEX_DIR / "inverted_index.json").read_text(encoding="utf-8"))
    merged = json.loads(_MERGED_FILE.read_text(encoding="utf-8"))
    all_kos = [ko for kos in merged.values() for ko in kos]
    return idf, inverted, all_kos


def retrieve_for_mission(
    mission_type: str,
    bottleneck: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    根据 mission_type 检索相关 KO，返回 brief_block 格式的列表。
    若索引不存在则返回空列表（静默降级，不影响 planning 主流程）。
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
    # 若有 bottleneck 补充到查询里
    if bottleneck and bottleneck not in query_text:
        query_text = f"{query_text} {bottleneck}"

    query_tokens = _tokenize(query_text)
    scores: dict[int, float] = defaultdict(float)

    for tok, tok_weight in query_tokens.items():
        if tok in inverted:
            idf_val = idf.get(tok, 0)
            for idx in inverted[tok]:
                ko = all_kos[idx]
                dim_bonus = 1.5 if preferred_dim and ko.get("dimension") == preferred_dim else 1.0
                ind_bonus = _ind_weight(ko)
                scores[idx] += idf_val * tok_weight * dim_bonus * ind_bonus

    results = []
    for idx, score in sorted(scores.items(), key=lambda x: -x[1]):
        ko = all_kos[idx]
        results.append({
            "type": "kb_insight",
            "score": round(score, 1),
            "insight": ko.get("insight", ""),
            "detail": ko.get("detail", ""),
            "quotation": str(ko.get("quotation", ""))[:120],
            "dimension": ko.get("dimension", ""),
            "source_title": ko.get("_session_title", ""),
            "industry": ko.get("_industry", []),
            "confidence": ko.get("confidence", ""),
        })
        if len(results) >= top_k:
            break

    return results
