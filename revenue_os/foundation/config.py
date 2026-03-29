from __future__ import annotations

import os
from pathlib import Path


def revenue_os_root() -> Path:
    """
    根路径解析优先级：
    1. REVENUE_OS_BASE_DIR 环境变量（iCloud Revenue OS 目录）
    2. 默认 → 当前 repo 根（xhs-playbook）
    """
    env = os.environ.get("REVENUE_OS_BASE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # xhs-playbook repo: foundation/config.py is at revenue_os/foundation/config.py
    return Path(__file__).resolve().parents[2]


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


REVENUE_OS_ROOT = revenue_os_root()
BUSINESS_LIBRARY_ROOT = REVENUE_OS_ROOT
CONTRACTS_ROOT = REVENUE_OS_ROOT / "contracts" / "revenue_os"
RUNTIME_ROOT = REVENUE_OS_ROOT / "runtime" / "revenue_os"
RAW_DATA_ROOT = REVENUE_OS_ROOT / "raw_data"
RAW_SOURCE_ROOT = RAW_DATA_ROOT / "source"
RAW_SOURCE_AUTO_ROOT = RAW_DATA_ROOT / "source_auto"
EXTRACTED_ROOT = RAW_DATA_ROOT / "extracted"
USERS_ROOT = RAW_DATA_ROOT / "users"
USERS_AUTO_ROOT = RAW_DATA_ROOT / "users_auto"
CREATOR_AUTO_ROOT = RAW_DATA_ROOT / "creator_auto"
KNOWLEDGE_ROOT = REVENUE_OS_ROOT / "knowledge_base"
KNOWLEDGE_PERSKU_ROOT = first_existing_path(
    KNOWLEDGE_ROOT / "canonical" / "per_sku",
    KNOWLEDGE_ROOT / "per_sku",
)
ANALYSIS_ROOT = REVENUE_OS_ROOT / "analysis"
DOCS_ROOT = REVENUE_OS_ROOT / "docs"
SCRIPTS_ROOT = REVENUE_OS_ROOT / "scripts"
REPORTS_ROOT = RUNTIME_ROOT / "reports"
ACQUISITION_ROOT = RUNTIME_ROOT / "acquisition"
ACQUISITION_INBOX_ROOT = RAW_DATA_ROOT / "inbox" / "qianfan_downloads"
DEFAULT_QIANFAN_BROWSER = "chrome"
DEFAULT_QIANFAN_DOWNLOAD_DIR = Path.home() / "Downloads"
LE_FOND_CONTENT_START_DATE = "2025-10-18"

ARTIFACT_DIRS = {
    "source_snapshot_manifest": RUNTIME_ROOT / "manifests" / "source_snapshots",
    "planner_bundle_manifest": RUNTIME_ROOT / "manifests" / "bundles",
    "active_runtime_manifest": RUNTIME_ROOT / "manifests" / "active",
    "run_index_manifest": RUNTIME_ROOT / "indexes",
    "entity_registry": RUNTIME_ROOT / "registries" / "entities",
    "metric_registry": RUNTIME_ROOT / "registries" / "metrics",
    "anomaly_gate_result": RUNTIME_ROOT / "states" / "anomaly",
    "current_state": RUNTIME_ROOT / "states" / "current",
    "mission_plan": RUNTIME_ROOT / "plans" / "missions",
    "planner_decision_ledger": RUNTIME_ROOT / "plans" / "ledgers",
    "execution_package": RUNTIME_ROOT / "execution" / "packages",
    "experiment_record": RUNTIME_ROOT / "experiments" / "records",
    "execution_completion_record": RUNTIME_ROOT / "experiments" / "completions",
    "experiment_result": RUNTIME_ROOT / "experiments" / "results",
    "pattern_object": RUNTIME_ROOT / "learning" / "patterns",
    "promotion_decision": RUNTIME_ROOT / "learning" / "promotions",
    "planner_eval_record": RUNTIME_ROOT / "eval" / "planner",
    "post_feedback_report": RUNTIME_ROOT / "analysis" / "post_feedback",
    "normalized_first_party": RUNTIME_ROOT / "normalized" / "first_party",
    "normalized_benchmark": RUNTIME_ROOT / "normalized" / "benchmark",
    "normalized_official_rules": RUNTIME_ROOT / "normalized" / "official_rules",
    "normalized_brand_truth": RUNTIME_ROOT / "normalized" / "brand_truth",
    "alias_resolution_report": RUNTIME_ROOT / "registries" / "alias_reports",
    "reconcile_report": REPORTS_ROOT / "reconcile",
    "acquisition_run_manifest": RUNTIME_ROOT / "acquisition" / "runs",
    "acquired_file_record": RUNTIME_ROOT / "acquisition" / "files",
    "surface_export_record": RUNTIME_ROOT / "acquisition" / "surfaces",
    "download_reconcile_report": RUNTIME_ROOT / "acquisition" / "reconcile",
    "source_freshness_record": RUNTIME_ROOT / "acquisition" / "freshness",
    "surface_proof_record": RUNTIME_ROOT / "acquisition" / "proofs",
    "proof_batch_report": RUNTIME_ROOT / "acquisition" / "proof_batches",
    "visual_fill_report": RUNTIME_ROOT / "acquisition" / "visual_fill",
    "acquisition_coverage_report": RUNTIME_ROOT / "acquisition" / "coverage",
    "qianfan_discovery_report": RUNTIME_ROOT / "acquisition" / "discovery",
    "acquisition_frontier_report": RUNTIME_ROOT / "acquisition" / "frontier",
    "phase_progress_report": REPORTS_ROOT / "progress",
    "cadence_stability_report": REPORTS_ROOT / "stability",
    "cadence_result": RUNTIME_ROOT / "cadence",
}

LOCKS_ROOT = RUNTIME_ROOT / "locks"

DEFAULT_THRESHOLDS = {
    "shop_visit_to_pay_cvr_low": 0.02,
    "product_click_to_pay_cvr_low": 0.03,
    "hero_sku_first_buy_cvr_low": 0.025,
    "aov_low": 300.0,
    "refund_rate_high": 0.15,
    "inquiry_to_pay_cvr_low": 0.20,
    "search_opportunity_ctr": 0.10,
    "min_orders_for_confidence": 10,
    "sample_floor_orders": 5,
    "source_completeness_warning": 0.85,
    "source_completeness_red": 0.70,
    "benchmark_stale_days": 30,
    "refund_order_month_lag": 1,
    "creator_home_stale_days": 7,
    "creator_note_manager_stale_days": 14,
}

REPLAY_THRESHOLDS = {
    "planner_primary_mission_match": 0.70,
    "guardrail_violation_rate": 0.05,
    "capacity_mismatch_rate": 0.10,
    "false_rule_promotion_rate": 0.05,
    "schema_validity": 1.0,
    "snapshot_reproducibility": 1.0,
}
