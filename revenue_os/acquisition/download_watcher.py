from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable


SKIP_SUFFIXES = {'.crdownload', '.download', '.part', '.tmp'}


def snapshot_download_dir(download_dir: Path) -> dict[str, float]:
    return {str(path): path.stat().st_mtime for path in download_dir.iterdir() if path.is_file()}


def _stable(path: Path, stabilization_seconds: int) -> bool:
    size_1 = path.stat().st_size
    time.sleep(stabilization_seconds)
    if not path.exists():
        return False
    size_2 = path.stat().st_size
    return size_1 == size_2


def wait_for_new_downloads(
    download_dir: Path,
    before: dict[str, float],
    allowed_suffixes: tuple[str, ...],
    timeout_seconds: int,
    stabilization_seconds: int,
) -> list[Path]:
    deadline = time.time() + timeout_seconds
    allowed = {suffix.lower() for suffix in allowed_suffixes}

    def _scan_candidates() -> list[Path]:
        candidates = []
        for path in download_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if allowed and path.suffix.lower() not in allowed:
                continue
            if str(path) not in before or path.stat().st_mtime > before[str(path)]:
                candidates.append(path)
        return candidates

    while True:
        candidates = _scan_candidates()
        stable = [path for path in candidates if _stable(path, stabilization_seconds)]
        if stable:
            return sorted(stable)
        if time.time() >= deadline:
            break
        time.sleep(0.5)

    # One last relaxed pass helps avoid near-deadline races in staged mode.
    candidates = _scan_candidates()
    if candidates:
        stable = [path for path in candidates if _stable(path, max(1, stabilization_seconds))]
        if stable:
            return sorted(stable)
    return []
