from __future__ import annotations

from typing import Any



def build_search_interventions(state: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = state.get("evidence_summary", [])
    opportunities = state.get("search_opportunities", [])
    interventions: list[dict[str, Any]] = []
    for index, item in enumerate(opportunities[:3], start=1):
        interventions.append(
            {
                "id": f"action__keyword__{item['keyword_id']}",
                "action_family": "keyword_package",
                "title": f"Package search content and placement around {item['term']}",
                "priority": index,
                "diagnosis": f"{item['term']} shows intent and should be converted into note angle + keyword placement.",
                "owner_role": "writer",
                "estimated_effort": "S",
                "asset_dependencies": ["keyword_brief", "note_angle", "term_placement_rules"],
                "expected_metric_impact": ["search_ctr", "search_purchase_cvr"],
                "evidence_refs": evidence[:2],
            }
        )
    return interventions
