from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from revenue_os.acquisition.creator_catalog import CreatorSurfaceSpec
from revenue_os.acquisition.surface_catalog import SurfaceSpec
from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RAW_SOURCE_AUTO_ROOT, USERS_AUTO_ROOT
from revenue_os.foundation.ids import deterministic_id, short_hash
from revenue_os.foundation.time_utils import utc_now_iso


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def route_target_dir(surface: SurfaceSpec | CreatorSurfaceSpec) -> Path:
    if surface.route_family == 'source_auto':
        base = RAW_SOURCE_AUTO_ROOT
    elif surface.route_family == 'users_auto':
        base = USERS_AUTO_ROOT
    elif surface.route_family == 'creator_auto':
        base = CREATOR_AUTO_ROOT
    else:
        raise ValueError(f'Unsupported route_family: {surface.route_family}')
    target = base / surface.route_subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def route_downloaded_file(
    run_id: str,
    surface: SurfaceSpec | CreatorSurfaceSpec,
    source_path: Path,
    runner_mode: str = "native",
) -> dict[str, Any]:
    sha256 = _hash_file(source_path)
    target_dir = route_target_dir(surface)
    target_name = f"{source_path.stem}__{short_hash([sha256])}{source_path.suffix.lower()}"
    target_path = target_dir / target_name
    if not target_path.exists():
        shutil.copy(source_path, target_path)
    return {
        'schema_version': '1.0.0',
        'object_type': 'acquired_file_record',
        'file_id': deterministic_id('acqfile', run_id, surface.name, sha256),
        'run_id': run_id,
        'surface_name': surface.name,
        'export_format': surface.export_format,
        'downloaded_at': utc_now_iso(),
        'source_path': str(source_path),
        'route_target': str(target_path),
        'sha256': sha256,
        'filesize': source_path.stat().st_size,
        'browser_mode': 'manual_compatible',
        'runner_mode': runner_mode,
        'source_url': surface.source_url,
        'retry_count': 0,
        'source_of_truth': 'acquisition acquired file router',
        'freshness_policy': {'immutable': True},
        'validator': 'revenue_os.foundation.contracts.validate_contract_document',
        'failure_mode': 'blocking',
    }
