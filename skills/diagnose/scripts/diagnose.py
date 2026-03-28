#!/usr/bin/env python3
"""
/diagnose — 账号健康诊断报告
"""
from __future__ import annotations
import json, sys, yaml
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from revenue_os.foundation.config import load_brand_profile, DATA_ROOT, RUNTIME_ROOT
from revenue_os.normalization.state_normalizer import build_user_state
from revenue_os.modeling.health_scorer import compute_health_score
from revenue_os.knowledge.kb_retriever import retrieve_for_mission
from revenue_os.normalization.profile_builder import INDUSTRY_PAIN_POINTS, COLD_START_PRIORS

BENCHMARKS_PATH = ROOT / "knowledge_base/indices/benchmarks.json"


def _load_benchmarks() -> dict:
    if BENCHMARKS_PATH.exists():
        return json.loads(BENCHMARKS_PATH.read_text(encoding="utf-8"))
    return {}


def _flat_benchmarks(benchmarks: dict, user_state: dict) -> dict:
    """将分层 benchmarks 展平为 {metric: {p50:...}}，优先行业 > 阶段 > 全局"""
    flat = dict(benchmarks.get("global", {}))
    stage = user_state.get("stage", "")
    industry = user_state.get("industry", "通用")
    for m, v in benchmarks.get("by_stage", {}).get(stage, {}).items():
        flat[m] = {**flat.get(m, {}), **v}
    for m, v in benchmarks.get("by_industry", {}).get(industry, {}).items():
        flat[m] = {**flat.get(m, {}), **v}
    return flat


def _cold_start_report(user_state: dict, top_kos: list) -> str:
    stage = user_state.get("stage", "ramp_up")
    bm    = (user_state.get("business_model") or ["ecommerce"])[0]
    ind   = user_state.get("industry", "通用")
    prior = COLD_START_PRIORS.get((stage, bm), {})
    ind_hint = INDUSTRY_PAIN_POINTS.get(ind, INDUSTRY_PAIN_POINTS.get("通用", {}))

    lines = [
        "# Revenue OS 账号诊断报告（冷启动模式）",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 数据状态",
        "⚠️  核心指标不足，以下基于账号阶段和行业先验给出建议。",
        "    运行 `scripts/collect_data.sh` 补全真实数据后重新诊断。",
        "",
        "## 账号基本面",
        f"- 角色：{user_state.get('role', '—')}  |  行业：{ind}  |  阶段：{stage}",
        f"- 变现模式：{', '.join(user_state.get('business_model') or [])}",
    ]
    if prior.get("kb_hint"):
        lines += ["", "## 阶段洞察", prior["kb_hint"]]
    if ind_hint.get("pain"):
        lines += ["", "## 行业特点", ind_hint["pain"]]

    lines += ["", "## 基于行业+阶段先验的初步建议", ""]
    for i, ko in enumerate(top_kos[:3], 1):
        lines += [
            f"### 建议 {i}：{ko['insight']}",
            ko["detail"][:200] + ("…" if len(ko["detail"]) > 200 else ""),
            f"*来源：{ko['source_title'] or '官方课程'}*",
            "",
        ]
    lines += ["---", "**下一步**：补全指标数据 → 运行 /diagnose 获取精准诊断"]
    return "\n".join(lines)


def _full_report(health: dict, user_state: dict, top_kos: list) -> str:
    total = health["total_score"]
    dims  = health["dimension_scores"]
    bt    = health.get("bottleneck")
    ind   = user_state.get("industry", "通用")

    def bar(score: int) -> str:
        filled = round(score / 10)
        return "█" * filled + "░" * (10 - filled)

    def status(s: int) -> str:
        return "🟢" if s >= 70 else ("🟡" if s >= 50 else "🔴")

    DIM_CN = {"traffic":"流量","engagement":"互动","conversion":"转化","revenue":"变现","activity":"活跃度"}

    lines = [
        "# Revenue OS 账号诊断报告",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  |  数据覆盖：{health['data_coverage']}",
        "",
        f"## 健康总分：{total}/100  {status(total)}",
        "",
        "| 维度 | 得分 | 状态 |",
        "|------|------|------|",
    ]
    for d, s in dims.items():
        lines.append(f"| {DIM_CN.get(d, d)} | {s} {bar(s)} | {status(s)} |")

    if bt:
        m_val   = bt.get("current_value")
        m_bench = bt.get("benchmark_p50")
        gap_pct = round((m_bench - m_val) / m_bench * 100) if m_val and m_bench and m_bench > 0 else None
        lines += [
            "",
            "## 主要瓶颈",
            f"### 🔴 {DIM_CN.get(bt['dimension'], bt['dimension'])}维度薄弱（{bt['dimension_score']}分，低于总分 {bt['gap_vs_total']} 分）",
            "",
            f"**核心指标**：`{bt['primary_metric']}`",
        ]
        if m_val and m_bench:
            lines.append(f"- 当前值：{m_val:.3f}  |  行业{ind} P50 基准：{m_bench:.3f}" +
                         (f"  |  差距：-{gap_pct}%" if gap_pct else ""))

    if top_kos:
        lines += ["", "## KB 知识支撑（官方课程依据）", ""]
        for i, ko in enumerate(top_kos[:3], 1):
            lines += [
                f"### {i}. {ko['insight']}",
                ko["detail"][:250] + ("…" if len(ko["detail"]) > 250 else ""),
                f"*来源：{ko['source_title'] or '官方课程'}*",
                "",
            ]

    lines += ["---", "运行 `/brief` 获取本周3个执行行动"]
    return "\n".join(lines)


def run_diagnose() -> None:
    profile     = load_brand_profile()
    user_state  = build_user_state(profile)
    benchmarks  = _load_benchmarks()
    flat_bench  = _flat_benchmarks(benchmarks, user_state)

    is_cold = len(user_state.get("missing_metrics", [])) >= 4
    mission = profile.get("inferred", {}).get("primary_mission", "content_formula_scaling")

    top_kos = retrieve_for_mission(
        mission,
        bottleneck=user_state.get("weak_metrics", [None])[0],
        user_state=user_state,
        top_k=5,
    )

    if is_cold:
        report = _cold_start_report(user_state, top_kos)
    else:
        health = compute_health_score(user_state, flat_bench)
        report = _full_report(health, user_state, top_kos)

        # 保存 health 供 /brief 复用
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        (RUNTIME_ROOT / "last_diagnose.json").write_text(
            json.dumps({"health": health, "user_state_summary": {
                "stage": user_state["stage"], "industry": user_state["industry"],
                "primary_objective": user_state["primary_objective"],
                "inferred_mission": mission,
            }}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(report)
    out = RUNTIME_ROOT / "last_diagnose.md"
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\n报告已保存：{out}")


if __name__ == "__main__":
    run_diagnose()
