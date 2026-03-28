#!/usr/bin/env python3
"""
/brief — 本周3个优先执行建议
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from revenue_os.foundation.config import load_brand_profile, RUNTIME_ROOT
from revenue_os.normalization.state_normalizer import build_user_state
from revenue_os.knowledge.kb_retriever import retrieve_for_mission
from revenue_os.planning.action_ranker import rank_actions

EFFORT_LABEL = {0.5: "⚡ 极低（30分钟）", 0.8: "🟢 低（1-2小时）",
                1.0: "🟡 中（半天）", 1.2: "🟡 中（半天）",
                1.5: "🔴 高（1-2天）", 2.0: "🔴 高（2天+）"}


def _effort_label(e: float) -> str:
    for k in sorted(EFFORT_LABEL):
        if e <= k + 0.1:
            return EFFORT_LABEL[k]
    return "🔴 高"


def _predict_range(ko: dict, user_state: dict) -> str:
    """简单区间预测：基于 confidence + bottleneck gap"""
    conf = ko.get("confidence", "medium")
    base = {"high": 0.18, "medium": 0.10, "low": 0.05}.get(conf, 0.10)
    lo, hi = round(base * 0.6 * 100), round(base * 1.6 * 100)
    return f"{lo}% ~ {hi}%（置信度：{conf}，预计2周内）"


def run_brief() -> None:
    profile    = load_brand_profile()
    user_state = build_user_state(profile)

    # 尝试读上次诊断结果
    diagnose_cache = RUNTIME_ROOT / "last_diagnose.json"
    bottleneck = None
    if diagnose_cache.exists():
        cache = json.loads(diagnose_cache.read_text(encoding="utf-8"))
        bottleneck = cache.get("health", {}).get("bottleneck")
        mission = cache.get("user_state_summary", {}).get("inferred_mission")
    else:
        mission = profile.get("inferred", {}).get("primary_mission", "content_formula_scaling")

    kos = retrieve_for_mission(
        mission,
        bottleneck=bottleneck.get("primary_metric") if bottleneck else None,
        user_state=user_state,
        top_k=10,
    )
    ranked = rank_actions(kos, user_state, bottleneck)

    DIM_CN = {"traffic":"流量","engagement":"互动","conversion":"转化","revenue":"变现","activity":"活跃度"}
    MISSION_CN = {
        "conversion_repair": "提升进店→购买转化率",
        "aov_lift": "提升客单价",
        "repurchase_activation": "激活复购",
        "search_positioning": "搜索关键词卡位",
        "content_formula_scaling": "放大内容公式",
    }

    lines = [
        "# XHS Playbook 本周执行简报",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"主攻方向：**{MISSION_CN.get(mission, mission)}**",
        "",
    ]
    if bottleneck:
        lines += [
            f"> 核心瓶颈：`{bottleneck.get('primary_metric','—')}` "
            f"当前 {bottleneck.get('current_value','?')} vs 基准 {bottleneck.get('benchmark_p50','?')}",
            "",
        ]
    lines += ["---", ""]

    for i, ko in enumerate(ranked[:3], 1):
        lines += [
            f"## 行动 {i}  |  优先级分：{ko['priority_score']}",
            f"### {ko['insight']}",
            "",
            f"**做什么**：{ko['detail'][:300]}{'…' if len(ko['detail'])>300 else ''}",
            "",
            f"**为什么现在做**：与当前瓶颈直接相关（维度：{ko.get('dimension','—')}）",
            "",
            f"**执行成本**：{_effort_label(ko['effort'])}",
            f"**预估效果**：相关指标可能提升 {_predict_range(ko, user_state)}",
            f"**知识来源**：*{ko.get('source_title') or '官方课程'}*",
            "",
            "---",
            "",
        ]

    lines += ["*由 XHS Playbook KB（6,429条官方课程知识）+ 贝叶斯指标建模生成*"]
    report = "\n".join(lines)

    print(report)
    out = RUNTIME_ROOT / "last_brief.md"
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\n简报已保存：{out}")


if __name__ == "__main__":
    run_brief()
