from __future__ import annotations

import os
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import DEFAULT_QIANFAN_BROWSER, DEFAULT_QIANFAN_DOWNLOAD_DIR


BROWSER_APP_CANDIDATES = {
    "chrome": ["/Applications/Google Chrome.app", str(Path.home() / "Applications/Google Chrome.app")],
    "arc": ["/Applications/Arc.app", str(Path.home() / "Applications/Arc.app")],
    "edge": ["/Applications/Microsoft Edge.app", str(Path.home() / "Applications/Microsoft Edge.app")],
    "comet": ["/Applications/Comet.app", str(Path.home() / "Applications/Comet.app")],
}

BROWSER_PROFILE_HINTS = {
    "chrome": Path.home() / "Library/Application Support/Google/Chrome",
    "arc": Path.home() / "Library/Application Support/Arc",
    "edge": Path.home() / "Library/Application Support/Microsoft Edge",
    "comet": Path.home() / "Library/Application Support/Comet",
}

BROWSER_BUNDLE_IDS = {
    "chrome": "com.google.Chrome",
    "arc": "company.thebrowser.Browser",
    "edge": "com.microsoft.edgemac",
    "comet": "app.comet.browser",
}


class BrowserAutomationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserProfile:
    browser_name: str
    app_path: Path | None
    bundle_id: str | None
    profile_root: Path | None
    cookies_path: Path | None
    mode: str


def detect_browser_profile(preferred_browser: str | None = None) -> BrowserProfile:
    candidates = [preferred_browser.lower()] if preferred_browser else [DEFAULT_QIANFAN_BROWSER, "arc", "edge", "comet"]
    for browser_name in candidates:
        if not browser_name:
            continue
        bundle_id = BROWSER_BUNDLE_IDS.get(browser_name)
        for app_candidate in BROWSER_APP_CANDIDATES.get(browser_name, []):
            app_path = Path(app_candidate)
            if app_path.exists():
                profile_root = BROWSER_PROFILE_HINTS.get(browser_name)
                cookies_path = (profile_root / "Default" / "Cookies") if profile_root else None
                return BrowserProfile(browser_name, app_path, bundle_id, profile_root if profile_root and profile_root.exists() else None, cookies_path if cookies_path and cookies_path.exists() else None, "manual")
        if bundle_id:
            profile_root = BROWSER_PROFILE_HINTS.get(browser_name)
            cookies_path = (profile_root / "Default" / "Cookies") if profile_root else None
            return BrowserProfile(browser_name, None, bundle_id, profile_root if profile_root and profile_root.exists() else None, cookies_path if cookies_path and cookies_path.exists() else None, "manual")
    fallback_name = preferred_browser or DEFAULT_QIANFAN_BROWSER
    return BrowserProfile(fallback_name, None, BROWSER_BUNDLE_IDS.get(fallback_name), None, None, "manual")


def detect_browser_download_dir(preferred_browser: str | None = None) -> Path:
    profile = detect_browser_profile(preferred_browser)
    if profile.profile_root is not None:
        prefs_path = profile.profile_root / "Default" / "Preferences"
        if prefs_path.exists():
            try:
                prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
                configured = prefs.get("download", {}).get("default_directory")
                if configured:
                    return Path(configured).expanduser()
            except Exception:
                pass
    return DEFAULT_QIANFAN_DOWNLOAD_DIR


def ensure_download_dir(download_dir: Path | None = None) -> Path:
    target = (download_dir or detect_browser_download_dir()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    return target


def open_surface_in_browser(source_url: str, preferred_browser: str | None = None) -> BrowserProfile:
    profile = detect_browser_profile(preferred_browser)
    errors: list[str] = []
    if profile.app_path is not None:
        try:
            subprocess.run(["open", "-a", str(profile.app_path), source_url], check=True, capture_output=True, text=True)
            return profile
        except subprocess.CalledProcessError as exc:
            errors.append((exc.stderr or exc.stdout or str(exc)).strip())
    if profile.bundle_id:
        try:
            subprocess.run(["open", "-b", profile.bundle_id, source_url], check=True, capture_output=True, text=True)
            return profile
        except subprocess.CalledProcessError as exc:
            errors.append((exc.stderr or exc.stdout or str(exc)).strip())
    try:
        subprocess.run(["open", source_url], check=True, capture_output=True, text=True)
        return profile
    except subprocess.CalledProcessError as exc:
        errors.append((exc.stderr or exc.stdout or str(exc)).strip())
    detail = " | ".join(error for error in errors if error) or "No browser launch method succeeded"
    raise BrowserAutomationUnavailable(f"Failed to open browser for {profile.browser_name}: {detail}")


def npx_playwright_available() -> bool:
    return shutil.which("npx") is not None


def validate_browser_mode(browser_mode: str) -> None:
    if browser_mode not in {"manual", "staged", "browser"}:
        raise ValueError(f"Unsupported browser_mode: {browser_mode}")
    if browser_mode == "browser" and not npx_playwright_available():
        raise BrowserAutomationUnavailable("npx playwright is not available")


def browser_session_metadata(profile: BrowserProfile, download_dir: Path) -> dict[str, Any]:
    return {
        "browser_name": profile.browser_name,
        "app_path": str(profile.app_path) if profile.app_path else None,
        "bundle_id": profile.bundle_id,
        "profile_root": str(profile.profile_root) if profile.profile_root else None,
        "cookies_path": str(profile.cookies_path) if profile.cookies_path else None,
        "download_dir": str(download_dir),
        "mode": profile.mode,
    }
