from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from revenue_os.acquisition.creator_capture import acquire_creator
from revenue_os.acquisition.coverage import build_acquisition_coverage_report
from revenue_os.acquisition.bootstrap_sync import bootstrap_sync
from revenue_os.acquisition.creator_catalog import creator_cadence_surfaces_for_mode
from revenue_os.acquisition.export_runner import acquire_qianfan, resume_acquisition_run, run_creator_proof_batch, run_qianfan_proof_batch, validate_acquisition_run
from revenue_os.acquisition.frontier import build_frontier_report
from revenue_os.acquisition.sampling_policy import build_sampling_policy
from revenue_os.acquisition.navigation_discovery import run_interface_discovery
from revenue_os.acquisition.opencli_bridge import OpenCLIUnavailable
from revenue_os.acquisition.readiness import build_acquisition_readiness
from revenue_os.acquisition.visual_fill import run_visual_fill
from revenue_os.eval.replay import run_replay_eval
from revenue_os.execution.experiments import complete_experiment, register_experiment, score_experiment
from revenue_os.execution.packages import generate_execution_package
from revenue_os.foundation.config import ANALYSIS_ROOT, CREATOR_AUTO_ROOT, DEFAULT_QIANFAN_BROWSER, DEFAULT_QIANFAN_DOWNLOAD_DIR, DOCS_ROOT, EXTRACTED_ROOT, KNOWLEDGE_PERSKU_ROOT, KNOWLEDGE_ROOT, RAW_DATA_ROOT, RAW_SOURCE_AUTO_ROOT, USERS_AUTO_ROOT
from revenue_os.foundation.contracts import contract_versions
from revenue_os.foundation.ids import deterministic_id, readable_id, short_hash
from revenue_os.foundation.io import ensure_runtime_layout, file_fingerprint, latest_artifact, list_artifacts, object_path, read_artifact, read_json, run_context, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso
from revenue_os.ingest.brand_truth import build_brand_truth
from revenue_os.ingest.extracted import build_benchmark, build_first_party
from revenue_os.ingest.official_rules import build_official_rules
from revenue_os.learning.governance import decide_promotion
from revenue_os.learning.patterns import update_learning
from revenue_os.planning.planner import build_mission_plan
from revenue_os.registry.entities import build_entity_registry
from revenue_os.registry.metrics import build_metric_registry
from revenue_os.status.progress import build_phase_progress_report
from revenue_os.status.stability import build_cadence_stability_report
from revenue_os.state.anomaly import run_anomaly_gate
from revenue_os.state.current_state import build_current_state


DEFAULT_BUNDLE_ID = "bundle__default_v1"


def _stderr_summary(message: str) -> None:
    print(message, file=sys.stderr)


def _create_default_bundle() -> dict[str, Any]:
    path = object_path("planner_bundle_manifest", DEFAULT_BUNDLE_ID)
    base_payload = {
        "model_component_versions": {
            "metric_stabilizer": "p0.eb.v1",
            "post_feedback_engine": "p0.post_feedback.v1",
            "completion_aware_scorer": "p0.completion_bayes.v1",
        },
        "model_artifact_hashes": {},
        "calibration_artifact_refs": {
            "metric_stabilizer": "calibration__metric_stabilizer__p0.calibration.v1",
            "completion_aware_scorer": "calibration__completion_aware_scorer__p0.calibration.v1",
        },
        "activation_mode_by_component": {
            "metric_stabilizer": "shadow",
            "post_feedback_engine": "shadow",
            "completion_aware_scorer": "shadow",
        },
    }
    if path.exists():
        bundle = read_json(path)
        changed = False
        for key, default in base_payload.items():
            if key not in bundle:
                bundle[key] = default
                changed = True
        if changed:
            write_artifact("planner_bundle_manifest", bundle)
        return bundle
    bundle = {
        "schema_version": "1.0.0",
        "object_type": "planner_bundle_manifest",
        "bundle_id": DEFAULT_BUNDLE_ID,
        "name": "default-v1",
        "created_at": utc_now_iso(),
        "weights": {
            "business_impact": 1.4,
            "confidence": 1.0,
            "evidence_quality": 1.0,
            "execution_feasibility": 0.8,
            "timing_fit": 0.6,
        },
        "thresholds": {
            "secondary_min_score": 0.35,
            "release": {
                "planner_primary_mission_match": 0.70,
                "guardrail_violation_rate": 0.05,
                "capacity_mismatch_rate": 0.10,
                "false_rule_promotion_rate": 0.05,
                "schema_validity": 1.0,
                "snapshot_reproducibility": 1.0,
            },
        },
        **base_payload,
        "contract_versions": contract_versions(),
        "source_of_truth": "default bundle seeded from phase-1 technical spec",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("planner_bundle_manifest", bundle)
    return bundle


def _source_paths() -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted(EXTRACTED_ROOT.glob("*.json")))
    paths.extend(sorted((RAW_DATA_ROOT / "source").glob("**/*.xlsx")))
    paths.extend(sorted(RAW_SOURCE_AUTO_ROOT.glob("**/*.xlsx")))
    paths.extend(sorted((RAW_DATA_ROOT / "users").glob("**/*.pdf")))
    paths.extend(sorted(USERS_AUTO_ROOT.glob("**/*.pdf")))
    paths.extend(sorted(CREATOR_AUTO_ROOT.glob("**/*.json")))
    paths.extend(sorted(CREATOR_AUTO_ROOT.glob("**/*.xlsx")))
    paths.extend(sorted((KNOWLEDGE_PERSKU_ROOT).glob("**/*.json")))
    paths.extend(sorted((KNOWLEDGE_ROOT / "playbooks").glob("**/*.md")))
    paths.extend(sorted(DOCS_ROOT.glob("*.md")))
    paths.extend(sorted(ANALYSIS_ROOT.glob("*.md")))
    return [path for path in paths if path.is_file()]


def snapshot_create(mode: str) -> dict[str, Any]:
    ensure_runtime_layout()
    source_paths = _source_paths()
    sources = [file_fingerprint(path) for path in source_paths]
    date_label = utc_now_iso()[:10]
    source_hash = short_hash(item["sha256"] for item in sources)
    family_id = readable_id("snapshot", mode, date_label, source_hash)
    existing = [path for path in list_artifacts("source_snapshot_manifest") if path.stem.startswith(family_id)]
    rerun_index = len(existing) + 1
    snapshot = {
        "schema_version": "1.0.0",
        "object_type": "source_snapshot_manifest",
        "snapshot_id": f"{family_id}-r{rerun_index:02d}",
        "snapshot_family_id": family_id,
        "source_hash": source_hash,
        "rerun_index": rerun_index,
        "mode": mode,
        "created_at": utc_now_iso(),
        "as_of_date": date_label,
        "sources": sources,
        "source_counts": {
            "total": len(sources),
            "extracted_json": len(list(EXTRACTED_ROOT.glob("*.json"))),
            "raw_xlsx": len(list((RAW_DATA_ROOT / "source").glob("**/*.xlsx"))),
            "raw_xlsx_auto": len(list(RAW_SOURCE_AUTO_ROOT.glob("**/*.xlsx"))),
            "user_pdfs": len(list((RAW_DATA_ROOT / "users").glob("**/*.pdf"))),
            "user_pdfs_auto": len(list(USERS_AUTO_ROOT.glob("**/*.pdf"))),
            "creator_json_auto": len(list(CREATOR_AUTO_ROOT.glob("**/*.json"))),
            "creator_xlsx_auto": len(list(CREATOR_AUTO_ROOT.glob("**/*.xlsx"))),
        },
        "hash_algorithm": "sha256",
        "freshness_policy": {"max_age_days": 7, "required_for_modes": ["weekly", "monthly"]},
        "source_of_truth": "Business Library source/extracted/knowledge/doc files",
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("source_snapshot_manifest", snapshot)
    return snapshot


def state_build(snapshot_id: str, bundle_id: str) -> dict[str, Any]:
    _create_default_bundle()
    run_anomaly_gate(snapshot_id)
    return build_current_state(snapshot_id, bundle_id)


def _maybe_acquire(
    mode: str,
    acquire_mode: str,
    browser_mode: str,
    browser: str | None,
    download_dir: str | None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any] | None:
    if acquire_mode == "off":
        return None
    return acquire_qianfan(
        mode=mode,
        browser_mode=browser_mode if acquire_mode == "on" else acquire_mode,
        preferred_browser=browser,
        download_dir=download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
        from_date=from_date,
        to_date=to_date,
    )


def _maybe_acquire_qianfan(
    mode: str,
    acquire_mode: str,
    browser_mode: str,
    browser: str | None,
    download_dir: str | None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any] | None:
    if acquire_mode == "off":
        return None
    return acquire_qianfan(
        mode=mode,
        browser_mode=browser_mode if acquire_mode == "on" else acquire_mode,
        preferred_browser=browser,
        download_dir=download_dir,
        cadence_only=True,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )


def _maybe_acquire_creator(
    mode: str,
    acquire_mode: str,
    browser_mode: str,
    browser: str | None,
    download_dir: str | None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any] | None:
    if acquire_mode == "off":
        return None
    if not creator_cadence_surfaces_for_mode(mode):
        return None
    creator_mode = browser_mode if acquire_mode == "on" else acquire_mode
    return acquire_creator(
        mode=mode,
        preferred_browser=browser,
        cadence_only=True,
        browser_mode=creator_mode,
        download_dir=download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )


def _maybe_resume_partial(run_id: str | None, browser: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    manifest = read_artifact("acquisition_run_manifest", run_id)
    if manifest.get("status") not in {"partial_success", "error"}:
        return manifest
    return resume_acquisition_run(run_id, preferred_browser=browser)


def _run_proof_jobs(
    mode: str,
    proof_wave: str,
    proof_limit: int,
    browser_mode: str,
    browser: str | None,
    download_dir: str | None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any]:
    if proof_wave == "none":
        return {"qianfan_proof_batch_id": None, "creator_proof_batch_id": None}
    qianfan_batch = run_qianfan_proof_batch(
        mode=mode,
        wave=proof_wave,
        limit=proof_limit,
        browser_mode=browser_mode,
        preferred_browser=browser,
        download_dir=download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    creator_batch = run_creator_proof_batch(
        mode=mode,
        limit=max(1, min(proof_limit, 4)),
        browser_mode=browser_mode if browser_mode in {"browser", "manual", "staged"} else "browser",
        preferred_browser=browser,
        download_dir=download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    return {
        "qianfan_proof_batch_id": qianfan_batch["batch_id"],
        "creator_proof_batch_id": creator_batch["batch_id"],
        "qianfan_proof_status": qianfan_batch["status"],
        "creator_proof_status": creator_batch["status"],
    }


def _write_cadence_result(
    mode: str,
    bundle_id: str,
    snapshot_id: str | None,
    qianfan_run: dict[str, Any] | None,
    creator_run: dict[str, Any] | None,
    readiness: dict[str, Any],
    result_refs: dict[str, Any],
) -> dict[str, Any]:
    cadence = {
        "schema_version": "1.0.0",
        "object_type": "cadence_result",
        "cadence_id": deterministic_id("cadence", mode, snapshot_id or bundle_id, utc_now_iso()),
        "mode": mode,
        "created_at": utc_now_iso(),
        "bundle_id": bundle_id,
        "status": "blocked" if readiness["status"] == "red" and mode in {"daily", "weekly"} else ("partial_success" if readiness["partial_failures"] else "success"),
        "snapshot_id": snapshot_id,
        "state_id": result_refs.get("state_id"),
        "mission_id": result_refs.get("mission_id"),
        "package_id": result_refs.get("package_id"),
        "experiment_id": result_refs.get("experiment_id"),
        "eval_id": result_refs.get("eval_id"),
        "active_id": result_refs.get("active_id"),
        "qianfan_acquisition_run_id": qianfan_run.get("run_id") if qianfan_run else None,
        "creator_acquisition_run_id": creator_run.get("run_id") if creator_run else None,
        "acquisition_readiness_status": readiness["status"],
        "partial_failures": readiness["partial_failures"],
        "blocking_reasons": readiness["blocking_reasons"],
        "result_refs": result_refs,
        "source_of_truth": "dual-source cadence orchestration",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("cadence_result", cadence)
    return cadence


def promote_bundle(bundle_id: str) -> dict[str, Any]:
    eval_record = read_artifact("planner_eval_record", deterministic_id("eval", bundle_id))
    previous_active = latest_artifact("active_runtime_manifest")
    previous_bundle_id = previous_active.get("bundle_id") if previous_active else None

    if eval_record["pass_status"] == "pass":
        status = "active"
        effective_bundle_id = bundle_id
        attempted_bundle_id = None
        rollback_target_bundle_id = previous_bundle_id
    elif previous_bundle_id:
        status = "rolled_back"
        effective_bundle_id = previous_bundle_id
        attempted_bundle_id = bundle_id
        rollback_target_bundle_id = previous_bundle_id
    else:
        status = "rejected"
        effective_bundle_id = bundle_id
        attempted_bundle_id = bundle_id
        rollback_target_bundle_id = None

    active = {
        "schema_version": "1.0.0",
        "object_type": "active_runtime_manifest",
        "active_id": "active_runtime",
        "bundle_id": effective_bundle_id,
        "attempted_bundle_id": attempted_bundle_id,
        "activated_at": utc_now_iso(),
        "status": status,
        "previous_active_bundle_id": previous_bundle_id,
        "rollback_target_bundle_id": rollback_target_bundle_id,
        "release_decision": {
            "eval_id": eval_record["eval_id"],
            "pass_status": eval_record["pass_status"],
            "scores": eval_record["scores"],
        },
        "source_of_truth": "release gate decisions",
        "freshness_policy": {"max_age_days": 30},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("active_runtime_manifest", active)
    return active


def cadence_daily(
    bundle_id: str,
    acquire_mode: str = "on",
    browser_mode: str = "browser",
    browser: str | None = None,
    download_dir: str | None = None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
    proof_wave: str = "none",
    proof_limit: int = 3,
) -> dict[str, str]:
    qianfan_run = _maybe_acquire_qianfan(
        "daily",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    creator_run = _maybe_acquire_creator(
        "daily",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    snapshot = snapshot_create("daily")
    build_first_party(snapshot["snapshot_id"])
    build_benchmark(snapshot["snapshot_id"])
    build_official_rules(snapshot["snapshot_id"])
    build_brand_truth(snapshot["snapshot_id"])
    build_metric_registry(snapshot["snapshot_id"])
    build_entity_registry(snapshot["snapshot_id"])
    state = state_build(snapshot["snapshot_id"], bundle_id)
    readiness = build_acquisition_readiness(snapshot["snapshot_id"], "daily")
    result = {
        "snapshot_id": snapshot["snapshot_id"],
        "state_id": state["state_id"],
        "sampling_policy": build_sampling_policy("daily"),
    }
    proof = _run_proof_jobs(
        "daily",
        proof_wave,
        proof_limit,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    for key, value in proof.items():
        if value:
            result[key] = value
    cadence = _write_cadence_result("daily", bundle_id, snapshot["snapshot_id"], qianfan_run, creator_run, readiness, result)
    result["cadence_id"] = cadence["cadence_id"]
    result["acquisition_readiness_status"] = readiness["status"]
    if qianfan_run:
        result["qianfan_acquisition_run_id"] = qianfan_run["run_id"]
    if creator_run:
        result["creator_acquisition_run_id"] = creator_run["run_id"]
    return result


def cadence_weekly(
    bundle_id: str,
    acquire_mode: str = "on",
    browser_mode: str = "browser",
    browser: str | None = None,
    download_dir: str | None = None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
    proof_wave: str = "none",
    proof_limit: int = 3,
) -> dict[str, str]:
    qianfan_run = _maybe_acquire_qianfan(
        "weekly",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    creator_run = _maybe_acquire_creator(
        "weekly",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    qianfan_run = _maybe_resume_partial(qianfan_run.get("run_id") if qianfan_run else None, browser) if qianfan_run else None
    creator_run = _maybe_resume_partial(creator_run.get("run_id") if creator_run else None, browser) if creator_run else None
    snapshot = snapshot_create("weekly")
    build_first_party(snapshot["snapshot_id"])
    build_benchmark(snapshot["snapshot_id"])
    build_official_rules(snapshot["snapshot_id"])
    build_brand_truth(snapshot["snapshot_id"])
    build_metric_registry(snapshot["snapshot_id"])
    build_entity_registry(snapshot["snapshot_id"])
    state = state_build(snapshot["snapshot_id"], bundle_id)
    mission, _ = build_mission_plan(state["state_id"], bundle_id)
    package = generate_execution_package(mission["mission_id"])
    experiment = register_experiment(mission["mission_id"])
    result = {
        "snapshot_id": snapshot["snapshot_id"],
        "state_id": state["state_id"],
        "mission_id": mission["mission_id"],
        "package_id": package["package_id"],
        "experiment_id": experiment["experiment_id"],
        "sampling_policy": build_sampling_policy("weekly"),
    }
    readiness = build_acquisition_readiness(snapshot["snapshot_id"], "weekly")
    proof = _run_proof_jobs(
        "weekly",
        proof_wave,
        proof_limit,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    for key, value in proof.items():
        if value:
            result[key] = value
    cadence = _write_cadence_result("weekly", bundle_id, snapshot["snapshot_id"], qianfan_run, creator_run, readiness, result)
    result["cadence_id"] = cadence["cadence_id"]
    result["acquisition_readiness_status"] = readiness["status"]
    if qianfan_run:
        result["qianfan_acquisition_run_id"] = qianfan_run["run_id"]
    if creator_run:
        result["creator_acquisition_run_id"] = creator_run["run_id"]
    return result


def cadence_monthly(
    bundle_id: str,
    acquire_mode: str = "on",
    browser_mode: str = "browser",
    browser: str | None = None,
    download_dir: str | None = None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
    proof_wave: str = "none",
    proof_limit: int = 3,
) -> dict[str, str]:
    qianfan_run = _maybe_acquire_qianfan(
        "monthly",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    creator_run = _maybe_acquire_creator(
        "monthly",
        acquire_mode,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    qianfan_run = _maybe_resume_partial(qianfan_run.get("run_id") if qianfan_run else None, browser) if qianfan_run else None
    creator_run = _maybe_resume_partial(creator_run.get("run_id") if creator_run else None, browser) if creator_run else None
    snapshot = snapshot_create("monthly")
    build_first_party(snapshot["snapshot_id"])
    build_benchmark(snapshot["snapshot_id"])
    build_official_rules(snapshot["snapshot_id"])
    build_brand_truth(snapshot["snapshot_id"])
    build_metric_registry(snapshot["snapshot_id"])
    build_entity_registry(snapshot["snapshot_id"])
    state = state_build(snapshot["snapshot_id"], bundle_id)
    eval_record = run_replay_eval(bundle_id)
    active = promote_bundle(bundle_id)
    result = {
        "snapshot_id": snapshot["snapshot_id"],
        "state_id": state["state_id"],
        "eval_id": eval_record["eval_id"],
        "active_id": active["active_id"],
        "status": active["status"],
        "sampling_policy": build_sampling_policy("monthly"),
    }
    readiness = build_acquisition_readiness(snapshot["snapshot_id"], "monthly")
    proof = _run_proof_jobs(
        "monthly",
        proof_wave,
        proof_limit,
        browser_mode,
        browser,
        download_dir,
        runner_mode=runner_mode,
        opencli_command_template=opencli_command_template,
        opencli_site=opencli_site,
        opencli_auto_install=opencli_auto_install,
    )
    for key, value in proof.items():
        if value:
            result[key] = value
    cadence = _write_cadence_result("monthly", bundle_id, snapshot["snapshot_id"], qianfan_run, creator_run, readiness, result)
    result["cadence_id"] = cadence["cadence_id"]
    result["acquisition_readiness_status"] = readiness["status"]
    if qianfan_run:
        result["qianfan_acquisition_run_id"] = qianfan_run["run_id"]
    if creator_run:
        result["creator_acquisition_run_id"] = creator_run["run_id"]
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revenue_os")
    subparsers = parser.add_subparsers(dest="command")

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_sub = snapshot_parser.add_subparsers(dest="snapshot_command")
    create_snapshot = snapshot_sub.add_parser("create")
    create_snapshot.add_argument("--mode", choices=["daily", "weekly", "monthly"], required=True)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_sub = ingest_parser.add_subparsers(dest="ingest_command")
    ingest_first = ingest_sub.add_parser("first-party")
    ingest_first.add_argument("--snapshot", required=True)
    ingest_benchmark = ingest_sub.add_parser("benchmark")
    ingest_benchmark.add_argument("--snapshot", required=True)

    acquire_parser = subparsers.add_parser("acquire")
    acquire_sub = acquire_parser.add_subparsers(dest="acquire_command")
    acquire_qianfan_parser = acquire_sub.add_parser("qianfan")
    acquire_qianfan_parser.add_argument("--mode", choices=["daily", "weekly", "monthly"])
    acquire_qianfan_parser.add_argument("--surface")
    acquire_qianfan_parser.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="manual")
    acquire_qianfan_parser.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    acquire_qianfan_parser.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    acquire_qianfan_parser.add_argument("--runner", choices=["native", "opencli"], default="native")
    acquire_qianfan_parser.add_argument("--opencli-command-template")
    acquire_qianfan_parser.add_argument("--opencli-site")
    acquire_qianfan_parser.add_argument("--opencli-auto-install", action="store_true")
    acquire_qianfan_parser.add_argument("--from", dest="from_date")
    acquire_qianfan_parser.add_argument("--to", dest="to_date")
    acquire_qianfan_parser.add_argument("--force-visual-probe", action="store_true")
    acquire_creator_parser = acquire_sub.add_parser("creator")
    acquire_creator_parser.add_argument("--mode", choices=["daily", "weekly", "monthly"])
    acquire_creator_parser.add_argument("--surface", choices=["creator_home", "creator_note_manager", "creator_events", "creator_inspiration"])
    acquire_creator_parser.add_argument("--browser", choices=["chrome"], default=DEFAULT_QIANFAN_BROWSER)
    acquire_creator_parser.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="browser")
    acquire_creator_parser.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    acquire_creator_parser.add_argument("--runner", choices=["native", "opencli"], default="native")
    acquire_creator_parser.add_argument("--opencli-command-template")
    acquire_creator_parser.add_argument("--opencli-site")
    acquire_creator_parser.add_argument("--opencli-auto-install", action="store_true")
    acquire_creator_parser.add_argument("--force-visual-probe", action="store_true")
    acquire_resume = acquire_sub.add_parser("resume")
    acquire_resume.add_argument("--run", required=True)
    acquire_resume.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    acquire_validate = acquire_sub.add_parser("validate")
    acquire_validate.add_argument("--run", required=True)
    acquire_proof = acquire_sub.add_parser("proof")
    acquire_proof.add_argument("--source", choices=["qianfan", "creator", "both"], default="both")
    acquire_proof.add_argument("--mode", choices=["daily", "weekly", "monthly"], default="weekly")
    acquire_proof.add_argument("--wave", choices=["none", "core", "A", "B", "C", "D", "all"], default="all")
    acquire_proof.add_argument("--limit", type=int, default=5)
    acquire_proof.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="manual")
    acquire_proof.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    acquire_proof.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    acquire_proof.add_argument("--runner", choices=["native", "opencli"], default="native")
    acquire_proof.add_argument("--opencli-command-template")
    acquire_proof.add_argument("--opencli-site")
    acquire_proof.add_argument("--opencli-auto-install", action="store_true")
    acquire_coverage = acquire_sub.add_parser("coverage")
    acquire_coverage.add_argument("--source", choices=["qianfan", "creator", "both"], default="both")
    acquire_bootstrap = acquire_sub.add_parser("bootstrap")
    acquire_bootstrap.add_argument("--source", choices=["qianfan", "creator", "both"], default="both")
    acquire_discover = acquire_sub.add_parser("discover")
    acquire_discover.add_argument("--source", choices=["qianfan", "creator"], default="qianfan")
    acquire_discover.add_argument("--browser", choices=["chrome"], default="chrome")
    acquire_discover.add_argument("--seed-url", default=None)
    acquire_discover.add_argument("--max-pages", type=int, default=120)
    acquire_discover.add_argument("--max-depth", type=int, default=2)
    acquire_frontier = acquire_sub.add_parser("frontier")
    acquire_frontier.add_argument("--source", choices=["qianfan", "creator", "both"], default="both")
    acquire_frontier.add_argument("--lookback", type=int, default=20)
    acquire_sampling_policy = acquire_sub.add_parser("sampling-policy")
    acquire_sampling_policy.add_argument("--mode", choices=["daily", "weekly", "monthly"], required=True)
    acquire_visual_fill = acquire_sub.add_parser("visual-fill")
    acquire_visual_fill.add_argument("--source", choices=["qianfan", "creator", "both"], default="both")
    acquire_visual_fill.add_argument("--strategy", choices=["fallback"], default="fallback")

    status_parser = subparsers.add_parser("status")
    status_sub = status_parser.add_subparsers(dest="status_command")
    status_progress = status_sub.add_parser("progress")
    status_progress.add_argument("--phase", choices=["phase1", "phase2"], default="phase1")
    status_stability = status_sub.add_parser("stability")
    status_stability.add_argument("--days", type=int, default=14)

    registry_parser = subparsers.add_parser("registry")
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    build_entities = registry_sub.add_parser("build-entities")
    build_entities.add_argument("--snapshot", required=True)

    state_parser = subparsers.add_parser("state")
    state_sub = state_parser.add_subparsers(dest="state_command")
    build_state = state_sub.add_parser("build")
    build_state.add_argument("--snapshot", required=True)
    build_state.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)

    plan_parser = subparsers.add_parser("plan")
    plan_sub = plan_parser.add_subparsers(dest="plan_command")
    weekly_plan = plan_sub.add_parser("weekly")
    weekly_plan.add_argument("--state", required=True)
    weekly_plan.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)

    package_parser = subparsers.add_parser("package")
    package_sub = package_parser.add_subparsers(dest="package_command")
    generate_package = package_sub.add_parser("generate")
    generate_package.add_argument("--mission", required=True)

    experiment_parser = subparsers.add_parser("experiment")
    experiment_sub = experiment_parser.add_subparsers(dest="experiment_command")
    register_cmd = experiment_sub.add_parser("register")
    register_cmd.add_argument("--mission", required=True)
    complete_cmd = experiment_sub.add_parser("complete")
    complete_cmd.add_argument("--experiment", required=True)
    complete_cmd.add_argument("--status", choices=["shipped_full", "shipped_partial", "blocked", "skipped"], default="shipped_full")
    score_cmd = experiment_sub.add_parser("score")
    score_cmd.add_argument("--experiment", required=True)

    learning_parser = subparsers.add_parser("learning")
    learning_sub = learning_parser.add_subparsers(dest="learning_command")
    learning_update = learning_sub.add_parser("update")
    learning_update.add_argument("--window", required=True)

    eval_parser = subparsers.add_parser("eval")
    eval_sub = eval_parser.add_subparsers(dest="eval_command")
    replay = eval_sub.add_parser("replay")
    replay.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)

    release_parser = subparsers.add_parser("release")
    release_sub = release_parser.add_subparsers(dest="release_command")
    promote = release_sub.add_parser("promote")
    promote.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)

    cadence_parser = subparsers.add_parser("cadence")
    cadence_sub = cadence_parser.add_subparsers(dest="cadence_command")
    cadence_daily_parser = cadence_sub.add_parser("daily")
    cadence_daily_parser.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)
    cadence_daily_parser.add_argument("--acquire-mode", choices=["off", "on", "manual", "staged", "browser"], default="on")
    cadence_daily_parser.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="browser")
    cadence_daily_parser.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    cadence_daily_parser.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    cadence_daily_parser.add_argument("--runner", choices=["native", "opencli"], default="native")
    cadence_daily_parser.add_argument("--opencli-command-template")
    cadence_daily_parser.add_argument("--opencli-site")
    cadence_daily_parser.add_argument("--opencli-auto-install", action="store_true")
    cadence_daily_parser.add_argument("--proof-wave", choices=["none", "core", "A", "B", "C", "D", "all"], default="none")
    cadence_daily_parser.add_argument("--proof-limit", type=int, default=3)
    cadence_weekly_parser = cadence_sub.add_parser("weekly")
    cadence_weekly_parser.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)
    cadence_weekly_parser.add_argument("--acquire-mode", choices=["off", "on", "manual", "staged", "browser"], default="on")
    cadence_weekly_parser.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="browser")
    cadence_weekly_parser.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    cadence_weekly_parser.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    cadence_weekly_parser.add_argument("--runner", choices=["native", "opencli"], default="native")
    cadence_weekly_parser.add_argument("--opencli-command-template")
    cadence_weekly_parser.add_argument("--opencli-site")
    cadence_weekly_parser.add_argument("--opencli-auto-install", action="store_true")
    cadence_weekly_parser.add_argument("--proof-wave", choices=["none", "core", "A", "B", "C", "D", "all"], default="none")
    cadence_weekly_parser.add_argument("--proof-limit", type=int, default=3)
    cadence_monthly_parser = cadence_sub.add_parser("monthly")
    cadence_monthly_parser.add_argument("--bundle", default=DEFAULT_BUNDLE_ID)
    cadence_monthly_parser.add_argument("--acquire-mode", choices=["off", "on", "manual", "staged", "browser"], default="on")
    cadence_monthly_parser.add_argument("--browser-mode", choices=["manual", "staged", "browser"], default="browser")
    cadence_monthly_parser.add_argument("--browser", choices=["chrome", "arc", "edge", "comet"], default=DEFAULT_QIANFAN_BROWSER)
    cadence_monthly_parser.add_argument("--download-dir", default=str(DEFAULT_QIANFAN_DOWNLOAD_DIR))
    cadence_monthly_parser.add_argument("--runner", choices=["native", "opencli"], default="native")
    cadence_monthly_parser.add_argument("--opencli-command-template")
    cadence_monthly_parser.add_argument("--opencli-site")
    cadence_monthly_parser.add_argument("--opencli-auto-install", action="store_true")
    cadence_monthly_parser.add_argument("--proof-wave", choices=["none", "core", "A", "B", "C", "D", "all"], default="none")
    cadence_monthly_parser.add_argument("--proof-limit", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    ensure_runtime_layout()
    _create_default_bundle()
    subcommand = ""
    for key, value in vars(args).items():
        if key.endswith("_command") and value:
            subcommand = str(value)
            break
    run_id = deterministic_id("run", args.command, subcommand, utc_now_iso(), str(time.time_ns()))
    with run_context(run_id=run_id, command=" ".join([args.command, *(argv or [])]), inputs=vars(args)):
        if args.command == "snapshot" and args.snapshot_command == "create":
            snapshot = snapshot_create(args.mode)
            print(snapshot["snapshot_id"])
            _stderr_summary(f"snapshot family={snapshot['snapshot_family_id']} rerun={snapshot['rerun_index']}")
            return 0
        if args.command == "ingest" and args.ingest_command == "first-party":
            build_first_party(args.snapshot)
            build_official_rules(args.snapshot)
            build_brand_truth(args.snapshot)
            registry = build_metric_registry(args.snapshot)
            print(registry["registry_id"])
            _stderr_summary(f"first-party ingest completed for snapshot={args.snapshot}")
            return 0
        if args.command == "ingest" and args.ingest_command == "benchmark":
            build_benchmark(args.snapshot)
            print(args.snapshot)
            _stderr_summary(f"benchmark ingest completed for snapshot={args.snapshot}")
            return 0
        if args.command == "acquire" and args.acquire_command == "qianfan":
            if not args.mode and not args.surface:
                parser.error("acquire qianfan requires --mode or --surface")
            try:
                manifest = acquire_qianfan(
                    mode=args.mode,
                    surface_name=args.surface,
                    browser_mode=args.browser_mode,
                    preferred_browser=args.browser,
                    download_dir=args.download_dir,
                    from_date=args.from_date,
                    to_date=args.to_date,
                    force_visual_probe=args.force_visual_probe,
                    runner_mode=args.runner,
                    opencli_command_template=args.opencli_command_template,
                    opencli_site=args.opencli_site,
                    opencli_auto_install=args.opencli_auto_install,
                )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            print(manifest["run_id"])
            _stderr_summary(f"status={manifest['status']} runner={manifest.get('runner_mode', 'native')} files={len(manifest['downloaded_files'])}")
            return 0
        if args.command == "acquire" and args.acquire_command == "creator":
            if not args.mode and not args.surface:
                parser.error("acquire creator requires --mode or --surface")
            try:
                manifest = acquire_creator(
                    mode=args.mode,
                    surface_name=args.surface,
                    preferred_browser=args.browser,
                    browser_mode=args.browser_mode,
                    download_dir=args.download_dir,
                    force_visual_probe=args.force_visual_probe,
                    runner_mode=args.runner,
                    opencli_command_template=args.opencli_command_template,
                    opencli_site=args.opencli_site,
                    opencli_auto_install=args.opencli_auto_install,
                )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            print(manifest["run_id"])
            _stderr_summary(f"status={manifest['status']} runner={manifest.get('runner_mode', 'native')} files={len(manifest['downloaded_files'])}")
            return 0
        if args.command == "acquire" and args.acquire_command == "resume":
            manifest = resume_acquisition_run(args.run, preferred_browser=args.browser)
            print(manifest["run_id"])
            _stderr_summary(f"status={manifest['status']} files={len(manifest['downloaded_files'])}")
            return 0
        if args.command == "acquire" and args.acquire_command == "validate":
            report = validate_acquisition_run(args.run)
            print(report["reconcile_id"])
            _stderr_summary(f"issues={len(report['issues'])} completed={len(report['completed_surfaces'])}")
            return 0
        if args.command == "acquire" and args.acquire_command == "proof":
            q_batch = None
            c_batch = None
            try:
                if args.source in {"qianfan", "both"}:
                    q_batch = run_qianfan_proof_batch(
                        mode=args.mode,
                        wave=args.wave,
                        limit=args.limit,
                        browser_mode=args.browser_mode,
                        preferred_browser=args.browser,
                        download_dir=args.download_dir,
                        runner_mode=args.runner,
                        opencli_command_template=args.opencli_command_template,
                        opencli_site=args.opencli_site,
                        opencli_auto_install=args.opencli_auto_install,
                    )
                if args.source in {"creator", "both"}:
                    c_batch = run_creator_proof_batch(
                        mode=args.mode,
                        limit=args.limit,
                        browser_mode=args.browser_mode,
                        preferred_browser=args.browser,
                        download_dir=args.download_dir,
                        runner_mode=args.runner,
                        opencli_command_template=args.opencli_command_template,
                        opencli_site=args.opencli_site,
                        opencli_auto_install=args.opencli_auto_install,
                    )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            primary = (q_batch or c_batch)
            print(primary["batch_id"])
            _stderr_summary(
                f"qianfan={q_batch['status'] if q_batch else 'skip'} creator={c_batch['status'] if c_batch else 'skip'} "
                f"q_proven={len(q_batch['proven_surfaces']) if q_batch else 0} c_proven={len(c_batch['proven_surfaces']) if c_batch else 0}"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "coverage":
            report = build_acquisition_coverage_report(args.source)
            print(report["coverage_id"])
            _stderr_summary(
                f"qianfan={report['qianfan_summary']['proven']}/{report['qianfan_summary']['total']} "
                f"creator={report['creator_summary']['proven']}/{report['creator_summary']['total']} "
                f"visual_q={report['qianfan_visual_summary']['ready']}/{report['qianfan_visual_summary']['required']} "
                f"visual_c={report['creator_visual_summary']['ready']}/{report['creator_visual_summary']['required']} "
                f"missing={len(report['missing_surfaces'])} visual_missing={len(report['missing_visual_surfaces'])} "
                f"decision_complete={report['decision_complete_coverage_pct']}% "
                f"frontier_governance={report['frontier_governance_coverage_pct']}% "
                f"frontier_p0p1={report['frontier_p0p1_integration_pct']}% "
                f"coverage_v2={report['coverage_v2_pct']}%"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "bootstrap":
            manifest = bootstrap_sync(args.source)
            print(manifest["run_id"])
            _stderr_summary(
                f"status={manifest['status']} imported={manifest.get('imported_file_count', 0)} "
                f"families={len(manifest.get('completed_families', []))}"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "discover":
            report = run_interface_discovery(
                source_system=args.source,
                browser_name=args.browser,
                seed_url=args.seed_url,
                max_pages=args.max_pages,
                max_depth=args.max_depth,
            )
            print(report["report_id"])
            _stderr_summary(
                f"source={report['source_system']} visited={report['visited_page_count']} "
                f"discovered={report['discovered_url_count']} catalog={report['catalog_url_count']} "
                f"missing_url={len(report['missing_from_catalog_urls'])} "
                f"missing_labels={len(report['missing_from_catalog_click_labels'])} "
                f"api={len(report['discovered_api_endpoints'])}"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "frontier":
            report = build_frontier_report(source_filter=args.source, lookback=args.lookback)
            print(report["report_id"])
            counts = report["candidate_counts"]
            governance = report.get("governance_summary", {})
            _stderr_summary(
                f"status={report['status']} candidates={counts['total_candidates']} "
                f"missing_url_q={counts['qianfan_missing_urls']} missing_url_c={counts['creator_missing_urls']} "
                f"api_q={counts['qianfan_candidate_api_endpoints']} api_c={counts['creator_candidate_api_endpoints']} "
                f"classified={governance.get('classified_api_candidates', 0)}/{governance.get('total_api_candidates', 0)} "
                f"unknown={governance.get('unknown_api_candidates', 0)}"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "sampling-policy":
            policy = build_sampling_policy(args.mode)
            print(policy["policy_id"])
            _stderr_summary(
                f"mode={policy['mode']} recommendation={policy['recommendation']} "
                f"window_priority={','.join(policy['window_priority'])} surfaces={len(policy['surface_rules'])}"
            )
            return 0
        if args.command == "acquire" and args.acquire_command == "visual-fill":
            report = run_visual_fill(args.source, strategy=args.strategy)
            print(report["report_id"])
            _stderr_summary(
                f"status={report['status']} required={report['required_total_records']} "
                f"existing={report['existing_total_records']} created={report['created_total_records']}"
            )
            return 0
        if args.command == "status" and args.status_command == "progress":
            report = build_phase_progress_report(args.phase)
            print(report["progress_id"])
            _stderr_summary(
                f"overall={report['overall_progress_pct']}% status={report['overall_status']} "
                f"qianfan={report['coverage_summary']['qianfan_proven']}/{report['coverage_summary']['qianfan_total']} "
                f"creator={report['coverage_summary']['creator_proven']}/{report['coverage_summary']['creator_total']} "
                f"visual_q={report['coverage_summary']['qianfan_visual_ready']}/{report['coverage_summary']['qianfan_visual_required']} "
                f"visual_c={report['coverage_summary']['creator_visual_ready']}/{report['coverage_summary']['creator_visual_required']} "
                f"missing={report['coverage_summary']['missing_total']} visual_missing={report['coverage_summary']['visual_missing_total']} "
                f"decision_complete={report['coverage_summary']['decision_complete_coverage_pct']}% "
                f"coverage_v2={report['coverage_summary']['coverage_v2_pct']}% "
                f"frontier_governance={report['coverage_summary']['frontier_governance_coverage_pct']}% "
                f"frontier_p0p1={report['coverage_summary']['frontier_p0p1_integration_pct']}%"
            )
            return 0
        if args.command == "status" and args.status_command == "stability":
            report = build_cadence_stability_report(args.days)
            print(report["stability_id"])
            by_mode = report.get("by_mode", {})
            _stderr_summary(
                f"window={report['window_days']}d pass_status={report['pass_status']} total_runs={report['total_runs']} "
                f"weekly_non_blocked={by_mode.get('weekly', {}).get('non_blocked_runs', 0)} "
                f"monthly_non_blocked={by_mode.get('monthly', {}).get('non_blocked_runs', 0)} "
                f"blocked_rate={report['blocked_rate']} red_readiness_rate={report['red_readiness_rate']}"
            )
            return 0
        if args.command == "registry" and args.registry_command == "build-entities":
            registry = build_entity_registry(args.snapshot)
            print(registry["registry_id"])
            _stderr_summary(f"entity registry built for snapshot={args.snapshot}")
            return 0
        if args.command == "state" and args.state_command == "build":
            state = state_build(args.snapshot, args.bundle)
            print(state["state_id"])
            _stderr_summary(f"primary_bottleneck={state['primary_bottleneck']} planner_mode={state['anomaly_gate']['planner_mode']}")
            return 0
        if args.command == "plan" and args.plan_command == "weekly":
            mission, ledger = build_mission_plan(args.state, args.bundle)
            print(mission["mission_id"])
            _stderr_summary(f"primary={mission['primary_mission']['mission_type']} ledger={ledger['ledger_id']}")
            return 0
        if args.command == "package" and args.package_command == "generate":
            package = generate_execution_package(args.mission)
            print(package["package_id"])
            _stderr_summary(f"mission_type={package['mission_type']} actions={len(package['actions'])}")
            return 0
        if args.command == "experiment" and args.experiment_command == "register":
            experiment = register_experiment(args.mission)
            print(experiment["experiment_id"])
            _stderr_summary(f"status={experiment['status']} primary_metric={experiment['primary_metric']}")
            return 0
        if args.command == "experiment" and args.experiment_command == "complete":
            completion = complete_experiment(args.experiment, args.status)
            print(completion["completion_id"])
            _stderr_summary(f"status={completion['status']} minimum_subset={completion['minimum_subset_completed']}")
            return 0
        if args.command == "experiment" and args.experiment_command == "score":
            result = score_experiment(args.experiment)
            print(result["result_id"])
            _stderr_summary(f"outcome={result['outcome']} evidence={result['evidence_class']}")
            return 0
        if args.command == "learning" and args.learning_command == "update":
            patterns = update_learning(args.window)
            promotions = [decide_promotion(pattern["pattern_id"]) for pattern in patterns]
            primary_id = patterns[0]["pattern_id"] if patterns else args.window
            print(primary_id)
            _stderr_summary(f"patterns={len(patterns)} promotions={len(promotions)}")
            return 0
        if args.command == "eval" and args.eval_command == "replay":
            record = run_replay_eval(args.bundle)
            print(record["eval_id"])
            _stderr_summary(f"pass_status={record['pass_status']} match={record['scores']['planner_primary_mission_match']}")
            return 0
        if args.command == "release" and args.release_command == "promote":
            active = promote_bundle(args.bundle)
            print(active["active_id"])
            _stderr_summary(f"status={active['status']} bundle={active['bundle_id']}")
            return 0
        if args.command == "cadence" and args.cadence_command == "daily":
            try:
                result = cadence_daily(
                    args.bundle,
                    args.acquire_mode,
                    args.browser_mode,
                    args.browser,
                    args.download_dir,
                    args.runner,
                    args.opencli_command_template,
                    args.opencli_site,
                    args.opencli_auto_install,
                    args.proof_wave,
                    args.proof_limit,
                )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            print(result["state_id"])
            _stderr_summary(
                f"snapshot={result['snapshot_id']} readiness={result['acquisition_readiness_status']} "
                f"qianfan={result.get('qianfan_acquisition_run_id', 'off')} creator={result.get('creator_acquisition_run_id', 'off')} "
                f"qproof={result.get('qianfan_proof_batch_id', 'off')} cproof={result.get('creator_proof_batch_id', 'off')}"
            )
            return 0
        if args.command == "cadence" and args.cadence_command == "weekly":
            try:
                result = cadence_weekly(
                    args.bundle,
                    args.acquire_mode,
                    args.browser_mode,
                    args.browser,
                    args.download_dir,
                    args.runner,
                    args.opencli_command_template,
                    args.opencli_site,
                    args.opencli_auto_install,
                    args.proof_wave,
                    args.proof_limit,
                )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            print(result["mission_id"])
            _stderr_summary(
                f"snapshot={result['snapshot_id']} experiment={result['experiment_id']} readiness={result['acquisition_readiness_status']} "
                f"qianfan={result.get('qianfan_acquisition_run_id', 'off')} creator={result.get('creator_acquisition_run_id', 'off')} "
                f"qproof={result.get('qianfan_proof_batch_id', 'off')} cproof={result.get('creator_proof_batch_id', 'off')}"
            )
            return 0
        if args.command == "cadence" and args.cadence_command == "monthly":
            try:
                result = cadence_monthly(
                    args.bundle,
                    args.acquire_mode,
                    args.browser_mode,
                    args.browser,
                    args.download_dir,
                    args.runner,
                    args.opencli_command_template,
                    args.opencli_site,
                    args.opencli_auto_install,
                    args.proof_wave,
                    args.proof_limit,
                )
            except OpenCLIUnavailable as exc:
                _stderr_summary(str(exc))
                return 2
            print(result["eval_id"])
            _stderr_summary(
                f"active_status={result['status']} active_id={result['active_id']} readiness={result['acquisition_readiness_status']} "
                f"qianfan={result.get('qianfan_acquisition_run_id', 'off')} creator={result.get('creator_acquisition_run_id', 'off')} "
                f"qproof={result.get('qianfan_proof_batch_id', 'off')} cproof={result.get('creator_proof_batch_id', 'off')}"
            )
            return 0

    parser.error("Unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
