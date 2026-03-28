from __future__ import annotations

from typing import Any



def build_repurchase_interventions(state: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = state.get("evidence_summary", [])
    hero = state.get("hero_sku", {})
    return [
        {
            "id": "action__repurchase_bundle",
            "action_family": "repurchase_bundle",
            "title": f"Create repurchase bundle anchored on {hero.get('display_name', 'hero SKU')}",
            "priority": 1,
            "diagnosis": "Recent buyers need a second-order offer that increases repeat purchase probability and basket depth.",
            "owner_role": "merchant",
            "estimated_effort": "M",
            "asset_dependencies": ["bundle_copy", "segment_export", "offer_rules"],
            "expected_metric_impact": ["repurchase_rate", "aov"],
            "evidence_refs": evidence[:3],
        },
        {
            "id": "action__lifecycle_trigger",
            "action_family": "lifecycle_trigger",
            "title": "Set a timed follow-up trigger for recent first buyers",
            "priority": 2,
            "diagnosis": "Le Fond repeat purchase is event-triggered, not purely consumption-driven.",
            "owner_role": "operator",
            "estimated_effort": "S",
            "asset_dependencies": ["segment_export", "message_copy"],
            "expected_metric_impact": ["repurchase_rate"],
            "evidence_refs": evidence[:2],
        },
    ]
