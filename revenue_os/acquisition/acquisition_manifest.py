from __future__ import annotations

from typing import Any

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.time_utils import utc_now_iso


def build_surface_export_record(
    run_id: str,
    surface_name: str,
    time_window: str,
    export_format: str,
    browser_mode: str,
    runner_mode: str,
    source_url: str,
    status: str,
    downloaded_files: list[str],
    retry_count: int,
    error_code: str | None = None,
    runner_command: str | None = None,
) -> dict[str, Any]:
    return {
        'schema_version': '1.0.0',
        'object_type': 'surface_export_record',
        'surface_export_id': deterministic_id('surfaceexport', run_id, surface_name),
        'run_id': run_id,
        'surface_name': surface_name,
        'time_window': time_window,
        'export_format': export_format,
        'started_at': utc_now_iso(),
        'finished_at': utc_now_iso(),
        'status': status,
        'browser_mode': browser_mode,
        'runner_mode': runner_mode,
        'runner_command': runner_command,
        'source_url': source_url,
        'downloaded_files': downloaded_files,
        'error_code': error_code,
        'retry_count': retry_count,
        'source_of_truth': 'acquisition surface export attempt',
        'freshness_policy': {'immutable': True},
        'validator': 'revenue_os.foundation.contracts.validate_contract_document',
        'failure_mode': 'blocking',
    }


def build_reconcile_report(run_id: str, expected_surfaces: list[str], completed_surfaces: list[str], file_ids: list[str], issues: list[str]) -> dict[str, Any]:
    return {
        'schema_version': '1.0.0',
        'object_type': 'download_reconcile_report',
        'reconcile_id': deterministic_id('acqreconcile', run_id),
        'run_id': run_id,
        'created_at': utc_now_iso(),
        'expected_surfaces': expected_surfaces,
        'completed_surfaces': completed_surfaces,
        'acquired_file_ids': file_ids,
        'issues': issues,
        'source_of_truth': 'acquisition download reconcile',
        'freshness_policy': {'immutable': True},
        'validator': 'revenue_os.foundation.contracts.validate_contract_document',
        'failure_mode': 'blocking',
    }


def build_run_manifest(
    run_id: str,
    mode: str,
    browser_mode: str,
    runner_mode: str,
    browser_name: str | None,
    source_url: str,
    download_dir: str,
    surface_records: list[str],
    downloaded_files: list[str],
    status: str,
    error_code: str | None = None,
    runner_command_template: str | None = None,
) -> dict[str, Any]:
    return {
        'schema_version': '1.0.0',
        'object_type': 'acquisition_run_manifest',
        'run_id': run_id,
        'mode': mode,
        'started_at': utc_now_iso(),
        'finished_at': utc_now_iso(),
        'status': status,
        'browser_mode': browser_mode,
        'runner_mode': runner_mode,
        'browser_name': browser_name,
        'runner_command_template': runner_command_template,
        'source_url': source_url,
        'download_dir': download_dir,
        'surface_records': surface_records,
        'downloaded_files': downloaded_files,
        'error_code': error_code,
        'source_of_truth': 'acquisition runner',
        'freshness_policy': {'immutable': True},
        'validator': 'revenue_os.foundation.contracts.validate_contract_document',
        'failure_mode': 'blocking',
    }
