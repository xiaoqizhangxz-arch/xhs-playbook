from __future__ import annotations

from typing import Any



def build_conversion_interventions(state: dict[str, Any]) -> list[dict[str, Any]]:
    hero = state.get("hero_sku", {})
    evidence = state.get("evidence_summary", [])
    return [
        {
            "id": "action__refresh_shop_hero",
            "action_family": "shop_asset_refresh",
            "title": f"Refresh shop hero assets for {hero.get('display_name', 'hero SKU')}",
            "priority": 1,
            "diagnosis": "Shop visit to pay is the current bottleneck and hero SKU landing assets are under-leveraged.",
            "owner_role": "operator",
            "estimated_effort": "M",
            "asset_dependencies": ["shop_assets", "wearing_images", "social_proof_cards"],
            "expected_metric_impact": ["shop_visit_to_pay_cvr", "product_click_to_pay_cvr"],
            "evidence_refs": evidence[:3],
        },
        {
            "id": "action__pin_comment_path",
            "action_family": "comment_pathing",
            "title": "Pin comment path that narrows users into the hero SKU",
            "priority": 2,
            "diagnosis": "High-intent traffic needs a shorter path from note to product choice.",
            "owner_role": "operator",
            "estimated_effort": "S",
            "asset_dependencies": ["comment_copy", "product_link"],
            "expected_metric_impact": ["inquiry_to_pay_cvr", "shop_visit_to_pay_cvr"],
            "evidence_refs": evidence[:2],
        },
        {
            "id": "action__cs_binary_recommendation",
            "action_family": "cs_script",
            "title": "Switch customer service opener to binary recommendation flow",
            "priority": 3,
            "diagnosis": "Inquiry-to-pay conversion is likely script-sensitive and should be simplified.",
            "owner_role": "cs",
            "estimated_effort": "S",
            "asset_dependencies": ["cs_script", "faq_sheet"],
            "expected_metric_impact": ["inquiry_to_pay_cvr"],
            "evidence_refs": evidence[1:4],
        },
    ]
