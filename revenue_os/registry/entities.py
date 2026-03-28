from __future__ import annotations

from collections import defaultdict
from typing import Any

from revenue_os.foundation.ids import deterministic_id, readable_id
from revenue_os.foundation.io import object_path, read_json, write_artifact, write_json

SKU_HINTS = {
    "sol et luna": "日月同辉",
    "荣格日月耳钉": "日月同辉",
    "日月耳钉": "日月同辉",
    "赫尔墨斯权杖项链": "赫尔墨斯",
    "雅典娜之鸮项链": "雅典娜",
}

ALIAS_POLICY = {
    "sku": {"severity": "blocking", "evidence_effect": "block"},
    "keyword": {"severity": "warning", "evidence_effect": "degraded"},
    "post": {"severity": "info", "evidence_effect": "downweight"},
    "account": {"severity": "info", "evidence_effect": "downweight"},
}


def _normalize_text(value: str) -> str:
    return value.strip().lower()


def _canonical_name(name: str, sku_map: dict[str, str]) -> str:
    lowered = _normalize_text(name)
    if lowered in SKU_HINTS:
        return SKU_HINTS[lowered]
    for key in sku_map:
        if key and key.lower() in lowered:
            return key
    return name.strip()


def _alias_entry(alias: str, entity_id: str, entity_type: str, source_path: str, confidence: float) -> dict[str, Any]:
    policy = ALIAS_POLICY[entity_type]
    return {
        "alias": alias,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "source_path": source_path,
        "confidence": round(confidence, 2),
        "blocking_severity": policy["severity"],
        "evidence_effect": policy["evidence_effect"],
    }


def build_entity_registry(snapshot_id: str) -> dict[str, Any]:
    first_party = read_json(object_path("normalized_first_party", snapshot_id))
    benchmark = read_json(object_path("normalized_benchmark", snapshot_id))
    brand_truth = read_json(object_path("normalized_brand_truth", snapshot_id))
    sku_map = brand_truth.get("sku_map", {})

    entities: dict[tuple[str, str], dict[str, Any]] = {}
    aliases: list[dict[str, Any]] = []
    unresolved_aliases: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for item in first_party.get("sku_performance", {}).get("rows", []):
        raw_name = item.get("name", "")
        canonical = _canonical_name(raw_name, sku_map)
        entity_id = readable_id("sku", canonical)
        key = ("sku", entity_id)
        entities[key] = {
            "entity_id": entity_id,
            "entity_type": "sku",
            "canonical_name": canonical,
            "display_name": raw_name.strip() or canonical,
            "source_paths": [first_party.get("source_files", {}).get("sku_performance", "")],
            "confidence": 0.95,
            "blocking_severity": ALIAS_POLICY["sku"]["severity"],
        }
        aliases.append(_alias_entry(raw_name, entity_id, "sku", first_party.get("source_files", {}).get("sku_performance", ""), 0.95))
        if canonical != raw_name.strip():
            aliases.append(_alias_entry(canonical, entity_id, "sku", "brand_truth.sku_map", 0.9))

    for item in first_party.get("search_terms", {}).get("rows", []):
        term = item.get("term", "")
        if not term:
            continue
        entity_id = readable_id("keyword", term)
        key = ("keyword", entity_id)
        entities[key] = {
            "entity_id": entity_id,
            "entity_type": "keyword",
            "canonical_name": term,
            "display_name": term,
            "source_paths": [first_party.get("source_files", {}).get("search_terms", "")],
            "confidence": 0.85,
            "blocking_severity": ALIAS_POLICY["keyword"]["severity"],
        }
        aliases.append(_alias_entry(term, entity_id, "keyword", first_party.get("source_files", {}).get("search_terms", ""), 0.85))

    for post in first_party.get("content_performance", {}).get("posts", []):
        note_id = str(post.get("note_id") or post.get("post_id") or "")
        if not note_id:
            continue
        entity_id = readable_id("post", note_id)
        key = ("post", entity_id)
        entities[key] = {
            "entity_id": entity_id,
            "entity_type": "post",
            "canonical_name": note_id,
            "display_name": post.get("title") or note_id,
            "source_paths": [first_party.get("source_files", {}).get("posts_enriched", "")],
            "confidence": 0.8,
            "blocking_severity": ALIAS_POLICY["post"]["severity"],
        }
        aliases.append(_alias_entry(note_id, entity_id, "post", first_party.get("source_files", {}).get("posts_enriched", ""), 0.8))

    for account in benchmark.get("competitor_benchmarks", {}).get("accounts", []):
        name = account.get("name", "")
        if not name:
            continue
        entity_id = readable_id("account", name)
        key = ("account", entity_id)
        entities[key] = {
            "entity_id": entity_id,
            "entity_type": "account",
            "canonical_name": name,
            "display_name": name,
            "source_paths": [benchmark.get("source_files", {}).get("competitor_benchmarks", "")],
            "confidence": 0.75,
            "blocking_severity": ALIAS_POLICY["account"]["severity"],
        }
        aliases.append(_alias_entry(name, entity_id, "account", benchmark.get("source_files", {}).get("competitor_benchmarks", ""), 0.75))

    alias_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for alias in aliases:
        alias_groups[(alias["entity_type"], _normalize_text(alias["alias"]))].append(alias)
    for (entity_type, alias_text), hits in alias_groups.items():
        target_ids = {hit["entity_id"] for hit in hits}
        if len(target_ids) > 1:
            conflicts.append(
                {
                    "alias": alias_text,
                    "entity_type": entity_type,
                    "entity_ids": sorted(target_ids),
                    "severity": ALIAS_POLICY[entity_type]["severity"],
                }
            )
    for alias in aliases:
        if not alias["alias"].strip():
            unresolved_aliases.append({
                "alias": alias["alias"],
                "entity_type": alias["entity_type"],
                "severity": ALIAS_POLICY[alias["entity_type"]]["severity"],
            })

    registry = {
        "schema_version": "1.0.0",
        "object_type": "entity_registry",
        "registry_id": deterministic_id("registry", snapshot_id, "entity"),
        "created_at": snapshot_id,
        "entities": sorted(entities.values(), key=lambda item: (item["entity_type"], item["canonical_name"])),
        "aliases": sorted(aliases, key=lambda item: (item["entity_type"], item["alias"])),
        "unresolved_aliases": unresolved_aliases,
        "conflicts": conflicts,
        "source_of_truth": "brand_intelligence maps + normalized first_party + benchmark corpora",
        "freshness_policy": {"max_age_days": 30},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("entity_registry", registry)
    write_json(object_path("alias_resolution_report", snapshot_id), {
        "snapshot_id": snapshot_id,
        "alias_policy": ALIAS_POLICY,
        "conflicts": conflicts,
        "unresolved_aliases": unresolved_aliases,
    })
    return registry
