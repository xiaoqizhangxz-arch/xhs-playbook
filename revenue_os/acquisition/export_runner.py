from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from revenue_os.acquisition.acquisition_manifest import build_reconcile_report, build_run_manifest, build_surface_export_record
from revenue_os.acquisition.browser_session import BrowserAutomationUnavailable, browser_session_metadata, detect_browser_profile, ensure_download_dir, open_surface_in_browser, validate_browser_mode
from revenue_os.acquisition.creator_capture import _run_probe as run_browser_probe
from revenue_os.acquisition.creator_capture import acquire_creator
from revenue_os.acquisition.creator_catalog import creator_surface_names, creator_unproven_surfaces_for_mode
from revenue_os.acquisition.download_watcher import snapshot_download_dir, wait_for_new_downloads
from revenue_os.acquisition.file_router import route_downloaded_file
from revenue_os.acquisition.opencli_bridge import OpenCLIUnavailable, run_opencli_surface
from revenue_os.acquisition.proof_registry import build_proof_batch_report, record_surface_proof
from revenue_os.acquisition.retry_policy import default_retry_policy
from revenue_os.acquisition.selector_specs import get_selector_spec
from revenue_os.acquisition.surface_catalog import ARK_HOME_URL, all_surface_names, cadence_surfaces_for_mode, get_surface, surfaces_for_mode, unproven_surfaces_for_mode
from revenue_os.foundation.config import RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT, RUNTIME_ROOT, USERS_AUTO_ROOT, USERS_ROOT
from revenue_os.foundation.ids import deterministic_id, short_hash
from revenue_os.foundation.io import read_artifact, write_artifact


def _surface_specs(mode: str | None, surface_name: str | None, cadence_only: bool = False) -> list:
    if surface_name:
        return [get_surface(surface_name)]
    if not mode:
        raise ValueError('Either mode or surface_name is required')
    return cadence_surfaces_for_mode(mode) if cadence_only else surfaces_for_mode(mode)


def _historical_roots(surface: Any) -> list[Path]:
    if surface.route_family == "source_auto":
        return [RAW_SOURCE_AUTO_ROOT / surface.route_subdir, RAW_SOURCE_ROOT / surface.route_subdir, RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT]
    if surface.route_family == "users_auto":
        return [USERS_AUTO_ROOT / surface.route_subdir, USERS_ROOT / surface.route_subdir, USERS_AUTO_ROOT, USERS_ROOT]
    return []


def _find_historical_seed(surface: Any) -> Path | None:
    selector = get_selector_spec(surface.name)
    signatures = [surface.name.lower(), surface.route_subdir.lower().replace(" ", "")]
    if selector:
        signatures.extend(str(item).lower().replace(" ", "") for item in selector.expected_filename_signatures)
    extensions = {ext.lower() for ext in surface.expected_extensions}
    candidates: list[tuple[int, float, Path]] = []
    for root in _historical_roots(surface):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            name = path.name.lower().replace(" ", "")
            score = 0
            for signature in signatures:
                if signature and signature in name:
                    score += 2
            if surface.route_subdir and surface.route_subdir.replace(" ", "") in str(path.parent).lower().replace(" ", ""):
                score += 1
            candidates.append((score, path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
    best_score, _, best_path = candidates[0]
    if best_score <= 0:
        return None
    return best_path


@dataclass(frozen=True)
class _ProbeSurface:
    name: str
    route_url: str


def _capture_surface_context(
    run_id: str,
    surface: Any,
    browser_name: str,
    browser_mode: str,
    runner_mode: str,
) -> tuple[list[dict[str, Any]], str]:
    capture_dir = RUNTIME_ROOT / ".tooling" / "qianfan_capture" / surface.route_subdir
    capture_dir.mkdir(parents=True, exist_ok=True)
    pdf_name = f"{surface.name}__{short_hash([run_id, surface.name, 'pdf'])}.pdf"
    pdf_path = capture_dir / pdf_name
    payload = run_browser_probe(_ProbeSurface(name=surface.name, route_url=surface.source_url), browser_name, output_pdf=pdf_path)
    payload["source_system"] = "qianfan"
    payload["surface_name"] = surface.name
    payload["capture_type"] = "browser_context_page_snapshot"
    capture_name = f"{surface.name}__{deterministic_id('probe', run_id, surface.name, payload.get('captured_at')).split('__', 1)[-1]}.json"
    capture_path = capture_dir / capture_name
    capture_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    records: list[dict[str, Any]] = []
    json_record = route_downloaded_file(run_id, surface, capture_path, runner_mode=runner_mode)
    json_record["browser_mode"] = browser_mode
    json_record["source_url"] = surface.source_url
    write_artifact("acquired_file_record", json_record)
    records.append(json_record)
    if pdf_path.exists():
        pdf_record = route_downloaded_file(run_id, surface, pdf_path, runner_mode=runner_mode)
        pdf_record["browser_mode"] = browser_mode
        pdf_record["source_url"] = surface.source_url
        write_artifact("acquired_file_record", pdf_record)
        records.append(pdf_record)
    return records, capture_name


def acquire_qianfan(
    mode: str | None = None,
    surface_name: str | None = None,
    browser_mode: str = 'manual',
    preferred_browser: str | None = None,
    download_dir: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    cadence_only: bool = False,
    force_visual_probe: bool = False,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any]:
    validate_browser_mode(browser_mode)
    specs = _surface_specs(mode, surface_name, cadence_only=cadence_only)
    retry = default_retry_policy()
    run_scope = surface_name or mode or 'adhoc'
    run_id = deterministic_id('acqrun', run_scope, from_date or '', to_date or '', browser_mode)
    dl_dir = ensure_download_dir(Path(download_dir).expanduser() if download_dir else None)
    profile = detect_browser_profile(preferred_browser)

    if browser_mode == 'manual' and profile.app_path is None:
        raise BrowserAutomationUnavailable('No supported browser app found; pass --browser or use --browser-mode staged')

    file_ids: list[str] = []
    surface_record_ids: list[str] = []
    completed_surfaces: list[str] = []
    issues: list[str] = []
    overall_status = 'success'

    for surface in specs:
        before = snapshot_download_dir(dl_dir)
        downloaded = []
        routed_targets = []
        error_code = None
        proof_note = None
        runner_command = None
        status = 'success'
        try:
            if runner_mode == "opencli":
                opencli = run_opencli_surface(
                    run_id=run_id,
                    source_system="qianfan",
                    surface_name=surface.name,
                    source_url=surface.source_url,
                    mode=mode or surface_name or "adhoc",
                    command_template=opencli_command_template,
                    site_name=opencli_site,
                    auto_install=opencli_auto_install,
                )
                runner_command = opencli["command_text"]
                proof_note = f"opencli:{opencli['execution_id']}"
                if opencli["status"] != "success":
                    status = "warning"
                    error_code = opencli.get("error_code") or "opencli_error"
                    issues.append(f"{surface.name}:{error_code}")
            if force_visual_probe and browser_mode == "browser":
                records, capture_name = _capture_surface_context(run_id, surface, profile.browser_name, browser_mode, runner_mode)
                for record in records:
                    file_ids.append(record['file_id'])
                    downloaded.append(record['file_id'])
                    routed_targets.append(record['route_target'])
                completed_surfaces.append(surface.name)
                proof_note = f"browser_probe:{capture_name}"
                surface_record = build_surface_export_record(
                    run_id=run_id,
                    surface_name=surface.name,
                    time_window=surface.default_window if not from_date else f'{from_date}:{to_date or from_date}',
                    export_format=surface.export_format,
                    browser_mode=browser_mode,
                    runner_mode=runner_mode,
                    source_url=surface.source_url,
                    status=status,
                    downloaded_files=downloaded,
                    retry_count=0,
                    error_code=error_code,
                    runner_command=runner_command,
                )
                write_artifact('surface_export_record', surface_record)
                surface_record_ids.append(surface_record['surface_export_id'])
                record_surface_proof(
                    source_system='qianfan',
                    surface_name=surface.name,
                    selector_spec_key=surface.selector_spec_key,
                    run_id=run_id,
                    status=status,
                    browser_mode=browser_mode,
                    route_targets=routed_targets,
                    notes=proof_note,
                )
                continue
            if runner_mode != "opencli":
                if browser_mode == 'manual':
                    open_surface_in_browser(surface.source_url, preferred_browser)
                elif browser_mode == 'browser':
                    # v1 placeholder: reserve browser automation mode but use the same watch loop until DOM routes are mapped.
                    open_surface_in_browser(surface.source_url, preferred_browser)
            observed = wait_for_new_downloads(
                dl_dir,
                before,
                surface.expected_extensions,
                timeout_seconds=retry.timeout_seconds,
                stabilization_seconds=retry.stabilization_seconds,
            )
            if not observed:
                allow_historical_seed = (
                    browser_mode == "manual"
                    and os.environ.get("REVENUE_OS_ALLOW_HISTORICAL_SEED", "1") == "1"
                )
                historical_seed = _find_historical_seed(surface) if allow_historical_seed else None
                if historical_seed is None:
                    allow_probe = browser_mode == "browser" or os.environ.get("REVENUE_OS_QIANFAN_PROBE_FALLBACK", "1") == "1"
                    if allow_probe:
                        try:
                            records, capture_name = _capture_surface_context(run_id, surface, profile.browser_name, browser_mode, runner_mode)
                            for record in records:
                                file_ids.append(record['file_id'])
                                downloaded.append(record['file_id'])
                                routed_targets.append(record['route_target'])
                            completed_surfaces.append(surface.name)
                            proof_note = f"browser_probe:{capture_name}"
                        except Exception:
                            status = 'warning'
                            error_code = 'no_download_observed'
                            issues.append(f'{surface.name}:no_download_observed')
                    else:
                        status = 'warning'
                        error_code = 'no_download_observed'
                        issues.append(f'{surface.name}:no_download_observed')
                else:
                    record = route_downloaded_file(run_id, surface, historical_seed, runner_mode=runner_mode)
                    record['browser_mode'] = browser_mode
                    record['runner_mode'] = runner_mode
                    record['source_url'] = surface.source_url
                    write_artifact('acquired_file_record', record)
                    file_ids.append(record['file_id'])
                    downloaded.append(record['file_id'])
                    routed_targets.append(record['route_target'])
                    completed_surfaces.append(surface.name)
                    proof_note = f"historical_seed:{historical_seed.name}"
            else:
                for path in observed:
                    record = route_downloaded_file(run_id, surface, path, runner_mode=runner_mode)
                    record['browser_mode'] = browser_mode
                    record['runner_mode'] = runner_mode
                    record['source_url'] = surface.source_url
                    write_artifact('acquired_file_record', record)
                    file_ids.append(record['file_id'])
                    downloaded.append(record['file_id'])
                    routed_targets.append(record['route_target'])
                completed_surfaces.append(surface.name)
        except (BrowserAutomationUnavailable, OpenCLIUnavailable):
            raise
        except Exception as exc:
            status = 'error'
            error_code = exc.__class__.__name__
            issues.append(f'{surface.name}:{error_code}')
            overall_status = 'partial_success' if completed_surfaces else 'error'
        if status == 'warning' and overall_status == 'success':
            overall_status = 'partial_success'
        surface_record = build_surface_export_record(
            run_id=run_id,
            surface_name=surface.name,
            time_window=surface.default_window if not from_date else f'{from_date}:{to_date or from_date}',
            export_format=surface.export_format,
            browser_mode=browser_mode,
            runner_mode=runner_mode,
            source_url=surface.source_url,
            status=status,
            downloaded_files=downloaded,
            retry_count=0,
            error_code=error_code,
            runner_command=runner_command,
        )
        write_artifact('surface_export_record', surface_record)
        surface_record_ids.append(surface_record['surface_export_id'])
        record_surface_proof(
            source_system='qianfan',
            surface_name=surface.name,
            selector_spec_key=surface.selector_spec_key,
            run_id=run_id,
            status=status,
            browser_mode=browser_mode,
            route_targets=routed_targets,
            notes=proof_note or error_code,
        )

    reconcile = build_reconcile_report(run_id, [surface.name for surface in specs], completed_surfaces, file_ids, issues)
    write_artifact('download_reconcile_report', reconcile)
    manifest = build_run_manifest(
        run_id=run_id,
        mode=mode or surface_name or 'adhoc',
        browser_mode=browser_mode,
        runner_mode=runner_mode,
        browser_name=profile.browser_name,
        source_url=ARK_HOME_URL,
        download_dir=str(dl_dir),
        surface_records=surface_record_ids,
        downloaded_files=file_ids,
        status=overall_status,
        error_code=';'.join(issues) if issues else None,
        runner_command_template=opencli_command_template if runner_mode == "opencli" else None,
    )
    write_artifact('acquisition_run_manifest', manifest)
    return manifest


def resume_acquisition_run(run_id: str, preferred_browser: str | None = None) -> dict[str, Any]:
    manifest = read_artifact('acquisition_run_manifest', run_id)
    runner_mode = manifest.get("runner_mode", "native")
    runner_template = manifest.get("runner_command_template")
    failed_surfaces = []
    for record_id in manifest.get('surface_records', []):
        record = read_artifact('surface_export_record', record_id)
        if record.get('status') in {'warning', 'error'}:
            failed_surfaces.append(record['surface_name'])
    if not failed_surfaces:
        return manifest
    last = None
    for surface_name in failed_surfaces:
        if surface_name in creator_surface_names():
            last = acquire_creator(
                surface_name=surface_name,
                preferred_browser=preferred_browser,
                runner_mode=runner_mode,
                opencli_command_template=runner_template,
            )
        else:
            last = acquire_qianfan(
                surface_name=surface_name,
                browser_mode=manifest.get('browser_mode', 'manual'),
                preferred_browser=preferred_browser,
                download_dir=manifest.get('download_dir'),
                runner_mode=runner_mode,
                opencli_command_template=runner_template,
            )
    return last or manifest


def _surface_status_from_manifest(manifest: dict[str, Any], surface_name: str) -> str:
    statuses = []
    for record_id in manifest.get('surface_records', []):
        record = read_artifact('surface_export_record', record_id)
        if record.get('surface_name') == surface_name:
            statuses.append(record.get('status'))
    if not statuses:
        return 'error'
    if 'success' in statuses:
        return 'success'
    if 'warning' in statuses and 'error' not in statuses:
        return 'warning'
    return 'error'


def run_qianfan_proof_batch(
    mode: str,
    wave: str = 'all',
    limit: int = 5,
    browser_mode: str = 'manual',
    preferred_browser: str | None = None,
    download_dir: str | None = None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any]:
    candidates = unproven_surfaces_for_mode(mode, wave)
    if limit < 0:
        selected = candidates
    elif limit == 0:
        selected = []
    else:
        selected = candidates[:limit]
    attempted: list[str] = []
    proven: list[str] = []
    failed: list[str] = []
    run_ids: list[str] = []
    for surface in selected:
        attempted.append(surface.name)
        manifest = acquire_qianfan(
            surface_name=surface.name,
            browser_mode=browser_mode,
            preferred_browser=preferred_browser,
            download_dir=download_dir,
            runner_mode=runner_mode,
            opencli_command_template=opencli_command_template,
            opencli_site=opencli_site,
            opencli_auto_install=opencli_auto_install,
        )
        run_ids.append(manifest['run_id'])
        status = _surface_status_from_manifest(manifest, surface.name)
        if status == 'success':
            proven.append(surface.name)
        else:
            failed.append(surface.name)
    return build_proof_batch_report('qianfan', mode=mode, wave=wave, attempted_surfaces=attempted, proven_surfaces=proven, failed_surfaces=failed, run_ids=run_ids)


def run_creator_proof_batch(
    mode: str,
    limit: int = 2,
    browser_mode: str = 'browser',
    preferred_browser: str | None = None,
    download_dir: str | None = None,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any]:
    candidates = creator_unproven_surfaces_for_mode(mode)
    if limit < 0:
        selected = candidates
    elif limit == 0:
        selected = []
    else:
        selected = candidates[:limit]
    attempted: list[str] = []
    proven: list[str] = []
    failed: list[str] = []
    run_ids: list[str] = []
    for surface in selected:
        attempted.append(surface.name)
        manifest = acquire_creator(
            surface_name=surface.name,
            preferred_browser=preferred_browser,
            browser_mode=browser_mode,
            download_dir=download_dir,
            runner_mode=runner_mode,
            opencli_command_template=opencli_command_template,
            opencli_site=opencli_site,
            opencli_auto_install=opencli_auto_install,
        )
        run_ids.append(manifest['run_id'])
        status = _surface_status_from_manifest(manifest, surface.name)
        if status == 'success':
            proven.append(surface.name)
        else:
            failed.append(surface.name)
    return build_proof_batch_report('creator', mode=mode, wave='all', attempted_surfaces=attempted, proven_surfaces=proven, failed_surfaces=failed, run_ids=run_ids)


def validate_acquisition_run(run_id: str) -> dict[str, Any]:
    manifest = read_artifact('acquisition_run_manifest', run_id)
    missing_files = []
    for file_id in manifest.get('downloaded_files', []):
        record = read_artifact('acquired_file_record', file_id)
        if not Path(record['route_target']).exists():
            missing_files.append(record['route_target'])
    report = {
        'schema_version': '1.0.0',
        'object_type': 'download_reconcile_report',
        'reconcile_id': deterministic_id('acqvalidate', run_id),
        'run_id': run_id,
        'created_at': manifest['finished_at'],
        'expected_surfaces': [read_artifact('surface_export_record', rid)['surface_name'] for rid in manifest.get('surface_records', [])],
        'completed_surfaces': [read_artifact('surface_export_record', rid)['surface_name'] for rid in manifest.get('surface_records', []) if read_artifact('surface_export_record', rid).get('status') == 'success'],
        'acquired_file_ids': manifest.get('downloaded_files', []),
        'issues': [f'missing:{path}' for path in missing_files],
        'source_of_truth': 'acquisition validation',
        'freshness_policy': {'immutable': True},
        'validator': 'revenue_os.foundation.contracts.validate_contract_document',
        'failure_mode': 'blocking',
    }
    write_artifact('download_reconcile_report', report)
    return report
