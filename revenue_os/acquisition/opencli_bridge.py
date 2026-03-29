from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import RUNTIME_ROOT
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.time_utils import utc_now_iso


OPENCLI_NPM_PACKAGE = "@jackwener/opencli"
DEFAULT_OPENCLI_TIMEOUT_SECONDS = 180
OPENCLI_LOG_ROOT = RUNTIME_ROOT / ".tooling" / "opencli"


class OpenCLIUnavailable(RuntimeError):
    pass


def detect_opencli_binary() -> str | None:
    return shutil.which("opencli")


def _split_command(command: str) -> list[str]:
    return shlex.split(command.strip())


def _install_opencli() -> None:
    if shutil.which("npm") is None:
        raise OpenCLIUnavailable("npm is required to install opencli")
    subprocess.run(
        ["npm", "install", "-g", OPENCLI_NPM_PACKAGE],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_opencli(auto_install: bool = False) -> str:
    binary = detect_opencli_binary()
    if binary:
        return binary
    if not auto_install:
        raise OpenCLIUnavailable("opencli is not installed; install with npm install -g @jackwener/opencli")
    _install_opencli()
    binary = detect_opencli_binary()
    if not binary:
        raise OpenCLIUnavailable("opencli installation finished but binary is still missing")
    return binary


def render_command_template(
    *,
    template: str | None,
    source_system: str,
    surface_name: str,
    source_url: str,
    mode: str,
    site_name: str | None,
) -> list[str]:
    if template:
        rendered = template.format(
            source_system=source_system,
            surface_name=surface_name,
            source_url=source_url,
            mode=mode,
            site_name=site_name or source_system,
        )
        return _split_command(rendered)
    site = site_name or f"revenueos_{source_system}"
    return ["opencli", "explore", source_url, "--site", site]


def run_opencli_surface(
    *,
    run_id: str,
    source_system: str,
    surface_name: str,
    source_url: str,
    mode: str,
    command_template: str | None = None,
    site_name: str | None = None,
    timeout_seconds: int = DEFAULT_OPENCLI_TIMEOUT_SECONDS,
    auto_install: bool = False,
) -> dict[str, Any]:
    binary = ensure_opencli(auto_install=auto_install)
    command = render_command_template(
        template=command_template,
        source_system=source_system,
        surface_name=surface_name,
        source_url=source_url,
        mode=mode,
        site_name=site_name,
    )
    command[0] = binary

    started_at = utc_now_iso()
    start = time.monotonic()
    status = "success"
    error_code = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=os.environ.copy(),
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            status = "error"
            error_code = f"opencli_exit_{completed.returncode}"
    except subprocess.TimeoutExpired:
        status = "error"
        error_code = "opencli_timeout"
    except Exception as exc:  # pragma: no cover - defensive branch
        status = "error"
        error_code = exc.__class__.__name__
    finished_at = utc_now_iso()
    duration_ms = int((time.monotonic() - start) * 1000)

    execution_id = deterministic_id("opencli", run_id, source_system, surface_name, started_at)
    OPENCLI_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = OPENCLI_LOG_ROOT / f"{execution_id}.log"
    log_path.write_text(
        "\n".join(
            [
                f"command: {' '.join(command)}",
                f"status: {status}",
                f"error_code: {error_code or ''}",
                f"started_at: {started_at}",
                f"finished_at: {finished_at}",
                "",
                "stdout:",
                stdout,
                "",
                "stderr:",
                stderr,
            ]
        ),
        encoding="utf-8",
    )

    return {
        "execution_id": execution_id,
        "source_system": source_system,
        "surface_name": surface_name,
        "status": status,
        "error_code": error_code,
        "command": command,
        "command_text": " ".join(command),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "stdout_tail": stdout[-8000:],
        "stderr_tail": stderr[-8000:],
        "log_path": str(log_path),
    }
