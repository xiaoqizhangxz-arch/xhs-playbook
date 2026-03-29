from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from revenue_os.acquisition.acquisition_manifest import build_reconcile_report, build_run_manifest, build_surface_export_record
from revenue_os.acquisition.browser_session import BrowserAutomationUnavailable, detect_browser_profile, ensure_download_dir, open_surface_in_browser, validate_browser_mode
from revenue_os.acquisition.creator_catalog import CREATOR_APIS, CREATOR_HOME_URL, CreatorApiSpec, CreatorSurfaceSpec, creator_cadence_surfaces_for_mode, creator_surfaces_for_mode, get_creator_surface
from revenue_os.acquisition.download_watcher import snapshot_download_dir, wait_for_new_downloads
from revenue_os.acquisition.file_router import route_downloaded_file
from revenue_os.acquisition.opencli_bridge import OpenCLIUnavailable, run_opencli_surface
from revenue_os.acquisition.proof_registry import record_surface_proof
from revenue_os.acquisition.retry_policy import default_retry_policy
from revenue_os.acquisition.selector_specs import get_selector_spec
from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RUNTIME_ROOT
from revenue_os.foundation.ids import deterministic_id, short_hash
from revenue_os.foundation.io import read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


TOOLING_ROOT = RUNTIME_ROOT / ".tooling" / "creator_capture"
PYTHON_VENV_ROOT = TOOLING_ROOT / "py"
NODE_ROOT = TOOLING_ROOT / "node"
TMP_CAPTURE_ROOT = TOOLING_ROOT / "captures"


class CreatorCaptureUnavailable(RuntimeError):
    pass


def _python_bin() -> Path:
    return PYTHON_VENV_ROOT / "venv" / "bin" / "python"


def _ensure_python_tooling() -> Path:
    python_bin = _python_bin()
    if python_bin.exists():
        return python_bin
    PYTHON_VENV_ROOT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["python3", "-m", "venv", str(PYTHON_VENV_ROOT / "venv")], check=True)
    subprocess.run([str(python_bin), "-m", "pip", "install", "browser-cookie3"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return python_bin


def _ensure_node_tooling() -> Path:
    if shutil.which("npm") is None or shutil.which("node") is None:
        raise CreatorCaptureUnavailable("Node.js/npm is required for creator browser-context capture")
    NODE_ROOT.mkdir(parents=True, exist_ok=True)
    package_json = NODE_ROOT / "package.json"
    module_dir = NODE_ROOT / "node_modules" / "@playwright" / "test"
    if not package_json.exists():
        subprocess.run(["npm", "init", "-y"], cwd=NODE_ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not module_dir.exists():
        subprocess.run(["npm", "install", "@playwright/test@latest"], cwd=NODE_ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return NODE_ROOT


def _browser_cookie_func(browser_name: str) -> str:
    if browser_name != "chrome":
        raise CreatorCaptureUnavailable("Creator capture currently supports Chrome cookie reuse only")
    return "chrome"


def _dump_chrome_cookies(output_path: Path, browser_name: str) -> None:
    python_bin = _ensure_python_tooling()
    browser_func = _browser_cookie_func(browser_name)
    script = """
import json
import os
import browser_cookie3
from pathlib import Path

browser_func = getattr(browser_cookie3, os.environ['BROWSER_FUNC'])
cookies = []
for c in browser_func(domain_name='xiaohongshu.com'):
    cookies.append({
        'name': c.name,
        'value': c.value,
        'domain': c.domain,
        'path': c.path or '/',
        'expires': float(c.expires) if c.expires else -1,
        'httpOnly': bool((getattr(c, '_rest', {}) or {}).get('HttpOnly')),
        'secure': bool(c.secure),
        'sameSite': 'Lax',
    })
Path(os.environ['OUTPUT_PATH']).write_text(json.dumps(cookies), encoding='utf-8')
"""
    subprocess.run(
        [str(python_bin), "-c", script],
        check=True,
        env={**os.environ, "OUTPUT_PATH": str(output_path), "BROWSER_FUNC": browser_func},
    )


def _target_apis(surface: CreatorSurfaceSpec) -> list[CreatorApiSpec]:
    if surface.name == "creator_home":
        names = {
            "user_info",
            "account_base",
            "latest_note_data",
            "note_detail_new",
            "livedata_overview",
            "growthrights_batchquery",
            "activity_center_list",
            "create_guidance",
            "leaderboard_recommend",
        }
    elif surface.name == "creator_note_manager":
        names = {"user_info", "note_user_posted"}
    else:
        names = {"user_info"}
    return [api for api in CREATOR_APIS if api.name in names]


def _write_probe_script(script_path: Path, surface: CreatorSurfaceSpec, apis: list[CreatorApiSpec]) -> None:
    payload = {
        "surface_name": surface.name,
        "route_url": surface.route_url,
        "enable_pagination": surface.name == "creator_note_manager",
        "max_note_pages": 12,
        "targets": [{"name": api.name, "path": api.path} for api in apis],
    }
    script = f"""
const {{ chromium }} = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');

(async () => {{
  const config = {json.dumps(payload, ensure_ascii=False)};
  const cookies = JSON.parse(fs.readFileSync(process.env.COOKIES_JSON, 'utf-8'));
  const launchOptions = {{ headless: true }};
  if (process.env.PLAYWRIGHT_CHANNEL) {{
    launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
  }}
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext();
  await context.addCookies(cookies);
  const page = await context.newPage();
  const apiResults = [];
  page.on('response', async (resp) => {{
    const url = resp.url();
    const target = config.targets.find((item) => url.includes(item.path));
    if (!target) return;
    let body = '';
    try {{
      body = await resp.text();
    }} catch (error) {{
      body = '';
    }}
    apiResults.push({{
      name: target.name,
      url,
      status: resp.status(),
      method: resp.request().method(),
      body,
      request_signing: {{
        has_x_s: Boolean(resp.request().headers()['x-s']),
        has_x_s_common: Boolean(resp.request().headers()['x-s-common']),
        referer: resp.request().headers()['referer'] || '',
      }},
    }});
  }});
  try {{
    await page.goto(config.route_url, {{ waitUntil: 'domcontentloaded', timeout: 45000 }});
  }} catch (error) {{
    // Keep capture resilient; partial DOM + API interceptions are still useful.
  }}
  await page.waitForTimeout(4000);
  let pageTurns = 0;
  if (config.enable_pagination) {{
    for (let i = 0; i < config.max_note_pages - 1; i++) {{
      const candidates = [
        page.getByRole('button', {{ name: /下一页|下页|next/i }}),
        page.locator('button:has-text(\"下一页\")'),
        page.locator('[aria-label*=\"下一页\"]'),
        page.locator('.ant-pagination-next'),
      ];
      let clicked = false;
      for (const locator of candidates) {{
        try {{
          const item = locator.first();
          if ((await item.count()) === 0) continue;
          if (!(await item.isVisible())) continue;
          if (await item.isDisabled()) continue;
          await item.click({{ timeout: 2000 }});
          clicked = true;
          pageTurns += 1;
          await page.waitForTimeout(1800);
          break;
        }} catch (error) {{}}
      }}
      if (!clicked) break;
    }}
  }}
  const visualSignals = await page.evaluate(() => {{
    const compact = (value) => {{
      const raw = value == null
        ? ''
        : (typeof value === 'string'
            ? value
            : (typeof value === 'number'
                ? String(value)
                : (value.baseVal ? String(value.baseVal) : String(value))));
      return raw.replace(/\\s+/g, ' ').trim();
    }};
    const cssPath = (node) => {{
      if (!node || !node.tagName) return '';
      const tag = node.tagName.toLowerCase();
      const id = node.id ? `#${{node.id}}` : '';
      const cls = compact(node.className || '').split(' ').filter(Boolean).slice(0, 2).map((item) => `.${{item}}`).join('');
      return `${{tag}}${{id}}${{cls}}`;
    }};
    const summary = (node) => {{
      const text = compact(node.innerText || node.textContent || '').slice(0, 80);
      return {{
        tag: (node.tagName || '').toLowerCase(),
        role: node.getAttribute ? (node.getAttribute('role') || '') : '',
        class_name: compact(node.className || '').slice(0, 80),
        aria_label: node.getAttribute ? compact(node.getAttribute('aria-label') || '').slice(0, 80) : '',
        path: cssPath(node),
        text,
      }};
    }};
    const chartNodes = Array.from(
      document.querySelectorAll(
        'canvas, svg, [class*="chart"], [class*="Chart"], [id*="chart"], [data-chart], [aria-label*="图"], [aria-label*="趋势"]'
      )
    );
    const tableNodes = Array.from(document.querySelectorAll('table'));
    const kpiText = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let cursor = walker.nextNode();
    while (cursor && kpiText.length < 320) {{
      const text = compact(cursor.nodeValue);
      if (text && text.length <= 48 && /[0-9]/.test(text)) {{
        kpiText.push(text);
      }}
      cursor = walker.nextNode();
    }}
    const uniqueKpi = Array.from(new Set(kpiText)).slice(0, 120);
    return {{
      chart_node_count: chartNodes.length,
      canvas_count: chartNodes.filter((node) => (node.tagName || '').toLowerCase() === 'canvas').length,
      svg_count: chartNodes.filter((node) => (node.tagName || '').toLowerCase() === 'svg').length,
      chart_nodes: chartNodes.slice(0, 24).map(summary),
      table_count: tableNodes.length,
      table_summaries: tableNodes.slice(0, 8).map((table) => {{
        const rows = table.querySelectorAll('tr');
        const first = rows.length ? rows[0].innerText : '';
        return {{
          row_count: rows.length,
          col_count: rows.length ? rows[0].querySelectorAll('th,td').length : 0,
          header_preview: compact(first).slice(0, 120),
        }};
      }}),
      numeric_text_samples: uniqueKpi,
    }};
  }});
  const bodyText = await page.locator('body').innerText();
  const outputPdf = process.env.OUTPUT_PDF;
  if (outputPdf) {{
    const fullHeight = await page.evaluate(() => {{
      const body = document.body ? document.body.scrollHeight : 0;
      const html = document.documentElement ? document.documentElement.scrollHeight : 0;
      return Math.max(body, html, 3200);
    }});
    const paperHeight = Math.min(20000, fullHeight + 240);
    await page.pdf({{
      path: outputPdf,
      printBackground: true,
      preferCSSPageSize: false,
      width: '1920px',
      height: `${{paperHeight}}px`,
      margin: {{ top: '16px', right: '16px', bottom: '16px', left: '16px' }},
    }});
  }}
  const payloadOut = {{
    captured_at: new Date().toISOString(),
    title: await page.title(),
    url: page.url(),
    body_text: bodyText,
    pagination: {{
      enabled: Boolean(config.enable_pagination),
      max_note_pages: config.max_note_pages,
      page_turns: pageTurns,
      pages_observed: pageTurns + 1,
    }},
    visual_signals: visualSignals,
    api_results: apiResults,
  }};
  fs.writeFileSync(process.env.OUTPUT_JSON, JSON.stringify(payloadOut, null, 2), 'utf-8');
  await browser.close();
}})();
"""
    script_path.write_text(script, encoding="utf-8")


def _run_probe(surface: CreatorSurfaceSpec, browser_name: str, output_pdf: Path | None = None) -> dict[str, Any]:
    _ensure_node_tooling()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        cookies_json = tmp_root / "cookies.json"
        output_json = tmp_root / "output.json"
        script_path = tmp_root / "creator_probe.js"
        _dump_chrome_cookies(cookies_json, browser_name)
        _write_probe_script(script_path, surface, _target_apis(surface))
        env = {
            **os.environ,
            "COOKIES_JSON": str(cookies_json),
            "OUTPUT_JSON": str(output_json),
            "PLAYWRIGHT_MODULE": str(NODE_ROOT / "node_modules" / "@playwright" / "test"),
            "PLAYWRIGHT_CHANNEL": os.environ.get("REVENUE_OS_PLAYWRIGHT_CHANNEL", ""),
        }
        if output_pdf is not None:
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            env["OUTPUT_PDF"] = str(output_pdf)
        timeout_seconds = int(os.environ.get("REVENUE_OS_PROBE_TIMEOUT_SECONDS", "240") or 240)
        try:
            completed = subprocess.run(
                ["node", str(script_path)],
                cwd=NODE_ROOT,
                check=False,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CreatorCaptureUnavailable(
                f"probe timeout for {surface.name} after {timeout_seconds}s"
            ) from exc
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "")[-1200:]
            stdout_tail = (completed.stdout or "")[-1200:]
            raise CreatorCaptureUnavailable(
                f"probe command failed for {surface.name}: exit={completed.returncode}; stderr={stderr_tail!r}; stdout={stdout_tail!r}"
            )
        payload = json.loads(output_json.read_text(encoding="utf-8"))
        if output_pdf is not None:
            payload["page_pdf_path"] = str(output_pdf) if output_pdf.exists() else None
        return payload


def _extract_home_metrics(body_text: str) -> dict[str, str]:
    labels = [
        "曝光数",
        "观看数",
        "封面点击率",
        "视频完播率",
        "点赞数",
        "评论数",
        "收藏数",
        "分享数",
        "净涨粉",
        "新增关注",
        "取消关注",
        "主页访客",
    ]
    metrics: dict[str, str] = {}
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if line in labels:
            metrics[line] = lines[index + 1]
    return metrics


def _extract_note_rows(body_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"(?:(?P<duration>\d{2}:\d{2})\n)?"
        r"(?P<title>[^\n]+)\n"
        r"发布于 (?P<published_at>[^\n]+)\n"
        r"(?P<views>\d+)\n(?P<likes>\d+)\n(?P<saves>\d+)\n(?P<comments>\d+)\n(?P<shares>\d+)\n权限设置",
        re.MULTILINE,
    )
    rows: list[dict[str, str]] = []
    for match in pattern.finditer(body_text):
        rows.append({key: (value or "") for key, value in match.groupdict().items()})
    return rows


def _extract_note_rows_from_api(api_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    page_indexes: set[int] = set()
    total_note_count = None
    for result in api_results:
        if result.get("name") != "note_user_posted":
            continue
        try:
            body = json.loads(result.get("body") or "{}")
        except json.JSONDecodeError:
            continue
        data = body.get("data") or {}
        notes = data.get("notes") or []
        total_note_count = data.get("total") if isinstance(data.get("total"), int) else total_note_count
        url = result.get("url") or ""
        page_match = re.search(r"[?&]page=(\d+)", url)
        page_indexes.add(int(page_match.group(1))) if page_match else None
        for note in notes:
            rows.append(
                {
                    "duration": note.get("video_duration") or note.get("video_length") or "",
                    "title": str(note.get("display_title") or note.get("title") or "").strip(),
                    "published_at": str(note.get("time") or ""),
                    "views": str(note.get("view_count") or 0),
                    "likes": str(note.get("likes") or note.get("likes_count") or 0),
                    "saves": str(note.get("collected_count") or 0),
                    "comments": str(note.get("comments_count") or 0),
                    "shares": str(note.get("share_count") or 0),
                    "note_id": str(note.get("id") or ""),
                    "xsec_token": str(note.get("xsec_token") or ""),
                    "type": str(note.get("type") or ""),
                }
            )
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("note_id") or f"{row.get('title')}::{row.get('published_at')}"
        deduped[key] = row
    page_count_captured = max(page_indexes) + 1 if page_indexes else (1 if deduped else 0)
    truncated = bool(total_note_count and len(deduped) < total_note_count)
    expected_pages = math.ceil(total_note_count / max(len(deduped), 1)) if total_note_count and deduped else page_count_captured
    return {
        "rows": list(deduped.values()),
        "total_note_count": total_note_count,
        "page_count_captured": page_count_captured,
        "expected_page_count": expected_pages,
        "truncated": truncated,
    }


def _parse_capture(surface: CreatorSurfaceSpec, payload: dict[str, Any]) -> dict[str, Any]:
    body_text = payload.get("body_text", "")
    parsed: dict[str, Any] = {}
    parsed["visual_signals"] = payload.get("visual_signals", {})
    if surface.name == "creator_home":
        parsed["home_metrics"] = _extract_home_metrics(body_text)
    elif surface.name == "creator_note_manager":
        api_extract = _extract_note_rows_from_api(payload.get("api_results", []))
        parsed["note_rows"] = api_extract["rows"] or _extract_note_rows(body_text)
        note_count_match = re.search(r"全部笔记\((\d+)\)", body_text)
        parsed["total_note_count"] = api_extract["total_note_count"] or (int(note_count_match.group(1)) if note_count_match else None)
        parsed["page_count_captured"] = api_extract["page_count_captured"]
        parsed["expected_page_count"] = api_extract["expected_page_count"]
        parsed["truncated"] = api_extract["truncated"]
    elif surface.name in {"creator_events", "creator_inspiration"}:
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        parsed["highlights"] = [line for line in lines[:120] if len(line) >= 4][:30]
    return parsed


def _write_capture_file(surface: CreatorSurfaceSpec, payload: dict[str, Any]) -> Path:
    target_dir = TMP_CAPTURE_ROOT / surface.route_subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = short_hash([payload.get("captured_at", utc_now_iso()), surface.name, payload.get("url", "")])
    target_path = target_dir / f"{surface.name}__{digest}.json"
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def _capture_with_probe_to_records(
    run_id: str,
    surface: CreatorSurfaceSpec,
    browser_name: str,
    browser_mode: str,
    runner_mode: str,
) -> tuple[list[dict[str, Any]], str]:
    pdf_name = f"{surface.name}__{short_hash([run_id, surface.name, utc_now_iso(), 'pdf'])}.pdf"
    pdf_path = TMP_CAPTURE_ROOT / surface.route_subdir / pdf_name
    capture = _run_probe(surface, browser_name, output_pdf=pdf_path)
    capture["source_system"] = "creator_platform"
    capture["surface_name"] = surface.name
    capture["parsed"] = _parse_capture(surface, capture)
    raw_capture_path = _write_capture_file(surface, capture)
    records: list[dict[str, Any]] = []
    json_record = route_downloaded_file(run_id, surface, raw_capture_path, runner_mode=runner_mode)
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
    return records, raw_capture_path.name


def _find_creator_seed(surface: CreatorSurfaceSpec, download_dir: Path | None = None) -> Path | None:
    selector = get_selector_spec(surface.name)
    signatures = [surface.name.lower(), surface.route_subdir.lower().replace(" ", "")]
    if selector:
        signatures.extend(str(item).lower().replace(" ", "") for item in selector.expected_filename_signatures)
    extensions = {ext.lower() for ext in surface.expected_extensions} | {".json", ".xlsx", ".xls", ".csv"}
    roots = [CREATOR_AUTO_ROOT / surface.route_subdir, CREATOR_AUTO_ROOT]
    if download_dir:
        roots.extend([download_dir, download_dir / surface.route_subdir])
    roots.append(Path.home() / "Downloads")
    candidates: list[tuple[int, float, Path]] = []
    for root in roots:
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
        now = time.time()
        download_roots = [Path.home() / "Downloads"]
        if download_dir:
            download_roots.append(download_dir)
        recent = [
            item
            for item in candidates
            if now - item[1] <= 1800 and any(str(item[2]).startswith(str(root)) for root in download_roots)
        ]
        if not recent:
            return None
        recent.sort(key=lambda item: (item[1], str(item[2])), reverse=True)
        return recent[0][2]
    return best_path


def acquire_creator(
    mode: str | None = None,
    surface_name: str | None = None,
    preferred_browser: str | None = None,
    cadence_only: bool = False,
    browser_mode: str = "browser",
    download_dir: str | None = None,
    force_visual_probe: bool = False,
    runner_mode: str = "native",
    opencli_command_template: str | None = None,
    opencli_site: str | None = None,
    opencli_auto_install: bool = False,
) -> dict[str, Any]:
    validate_browser_mode(browser_mode)
    browser_name = preferred_browser or "chrome"
    profile = detect_browser_profile(browser_name)
    if profile.app_path is None and not profile.bundle_id:
        raise BrowserAutomationUnavailable("Chrome is required for creator acquisition")
    specs = [get_creator_surface(surface_name)] if surface_name else (
        creator_cadence_surfaces_for_mode(mode or "weekly") if cadence_only else creator_surfaces_for_mode(mode or "weekly")
    )
    run_id = deterministic_id("acqrun", "creator", surface_name or mode or "adhoc", utc_now_iso())
    file_ids: list[str] = []
    surface_record_ids: list[str] = []
    completed_surfaces: list[str] = []
    issues: list[str] = []
    overall_status = "success"
    retry = default_retry_policy()
    dl_dir = ensure_download_dir(Path(download_dir).expanduser()) if download_dir else ensure_download_dir()

    for surface in specs:
        status = "success"
        downloaded: list[str] = []
        routed_targets: list[str] = []
        error_code = None
        proof_note = None
        runner_command = None
        try:
            if runner_mode == "opencli":
                opencli = run_opencli_surface(
                    run_id=run_id,
                    source_system="creator",
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
            if force_visual_probe:
                records, raw_name = _capture_with_probe_to_records(run_id, surface, browser_name, "browser", runner_mode)
                for record in records:
                    downloaded.append(record["file_id"])
                    file_ids.append(record["file_id"])
                    routed_targets.append(record["route_target"])
                completed_surfaces.append(surface.name)
                proof_note = f"browser_probe:{raw_name}"
                surface_record = build_surface_export_record(
                    run_id=run_id,
                    surface_name=surface.name,
                    time_window=surface.default_window,
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
                write_artifact("surface_export_record", surface_record)
                surface_record_ids.append(surface_record["surface_export_id"])
                record_surface_proof(
                    source_system="creator",
                    surface_name=surface.name,
                    selector_spec_key=surface.selector_spec_key,
                    run_id=run_id,
                    status=status,
                    browser_mode=browser_mode,
                    route_targets=routed_targets,
                    notes=proof_note,
                )
                continue
            if browser_mode == "browser":
                try:
                    records, raw_name = _capture_with_probe_to_records(run_id, surface, browser_name, "browser", runner_mode)
                    for record in records:
                        downloaded.append(record["file_id"])
                        file_ids.append(record["file_id"])
                        routed_targets.append(record["route_target"])
                    completed_surfaces.append(surface.name)
                    proof_note = f"browser_probe:{raw_name}"
                except Exception:
                    raise
            else:
                before = snapshot_download_dir(dl_dir)
                if browser_mode == "manual" and runner_mode != "opencli":
                    open_surface_in_browser(surface.source_url, preferred_browser)
                observed = wait_for_new_downloads(
                    dl_dir,
                    before,
                    tuple(suffix for suffix in surface.expected_extensions if suffix.lower() != ".json"),
                    timeout_seconds=retry.timeout_seconds,
                    stabilization_seconds=retry.stabilization_seconds,
                )
                if not observed:
                    allow_historical_seed = (
                        browser_mode == "manual"
                        and os.environ.get("REVENUE_OS_ALLOW_HISTORICAL_SEED", "1") == "1"
                    )
                    historical_seed = _find_creator_seed(surface, dl_dir) if allow_historical_seed else None
                    if historical_seed is None:
                        allow_probe = browser_mode == "browser" or os.environ.get("REVENUE_OS_CREATOR_PROBE_FALLBACK", "1") == "1"
                        if allow_probe:
                            try:
                                records, raw_name = _capture_with_probe_to_records(run_id, surface, browser_name, browser_mode, runner_mode)
                                for record in records:
                                    record["runner_mode"] = runner_mode
                                for record in records:
                                    downloaded.append(record["file_id"])
                                    file_ids.append(record["file_id"])
                                    routed_targets.append(record["route_target"])
                                completed_surfaces.append(surface.name)
                                proof_note = f"browser_probe:{raw_name}"
                            except Exception:
                                status = "warning"
                                error_code = "no_download_observed"
                                issues.append(f"{surface.name}:no_download_observed")
                        else:
                            status = "warning"
                            error_code = "no_download_observed"
                            issues.append(f"{surface.name}:no_download_observed")
                    else:
                        record = route_downloaded_file(run_id, surface, historical_seed, runner_mode=runner_mode)
                        record["browser_mode"] = browser_mode
                        record["runner_mode"] = runner_mode
                        record["source_url"] = surface.source_url
                        write_artifact("acquired_file_record", record)
                        downloaded.append(record["file_id"])
                        file_ids.append(record["file_id"])
                        routed_targets.append(record["route_target"])
                        completed_surfaces.append(surface.name)
                        proof_note = f"historical_seed:{historical_seed.name}"
                else:
                    for path in observed:
                        record = route_downloaded_file(run_id, surface, path, runner_mode=runner_mode)
                        record["browser_mode"] = browser_mode
                        record["runner_mode"] = runner_mode
                        record["source_url"] = surface.source_url
                        write_artifact("acquired_file_record", record)
                        downloaded.append(record["file_id"])
                        file_ids.append(record["file_id"])
                        routed_targets.append(record["route_target"])
                    completed_surfaces.append(surface.name)
            if issues and overall_status == "success":
                overall_status = "partial_success"
        except (BrowserAutomationUnavailable, OpenCLIUnavailable) as exc:
            status = "error"
            error_code = exc.__class__.__name__
            issues.append(f"{surface.name}:{error_code}")
            overall_status = "partial_success" if completed_surfaces else "error"
        except Exception as exc:
            status = "error"
            error_code = exc.__class__.__name__
            issues.append(f"{surface.name}:{error_code}")
            overall_status = "partial_success" if completed_surfaces else "error"
        surface_record = build_surface_export_record(
            run_id=run_id,
            surface_name=surface.name,
            time_window=surface.default_window,
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
        write_artifact("surface_export_record", surface_record)
        surface_record_ids.append(surface_record["surface_export_id"])
        record_surface_proof(
            source_system="creator",
            surface_name=surface.name,
            selector_spec_key=surface.selector_spec_key,
            run_id=run_id,
            status=status,
            browser_mode=browser_mode,
            route_targets=routed_targets,
            notes=proof_note or error_code,
        )

    reconcile = build_reconcile_report(run_id, [surface.name for surface in specs], completed_surfaces, file_ids, issues)
    write_artifact("download_reconcile_report", reconcile)
    manifest = build_run_manifest(
        run_id=run_id,
        mode=mode or surface_name or "creator_adhoc",
        browser_mode=browser_mode,
        runner_mode=runner_mode,
        browser_name=browser_name,
        source_url=CREATOR_HOME_URL,
        download_dir=str(dl_dir if browser_mode != "browser" else CREATOR_AUTO_ROOT),
        surface_records=surface_record_ids,
        downloaded_files=file_ids,
        status=overall_status,
        error_code=";".join(issues) if issues else None,
        runner_command_template=opencli_command_template if runner_mode == "opencli" else None,
    )
    write_artifact("acquisition_run_manifest", manifest)
    return manifest


def latest_creator_capture(surface_name: str) -> dict[str, Any] | None:
    surface = get_creator_surface(surface_name)
    root = CREATOR_AUTO_ROOT / surface.route_subdir
    if not root.exists():
        return None
    items = sorted(root.glob("*.json"), key=lambda path: (path.stat().st_mtime, path.name))
    if not items:
        return None
    return json.loads(items[-1].read_text(encoding="utf-8"))


def latest_creator_export(surface_name: str) -> Path | None:
    surface = get_creator_surface(surface_name)
    root = CREATOR_AUTO_ROOT / surface.route_subdir
    if not root.exists():
        return None
    items = sorted(
        [path for path in root.iterdir() if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}],
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not items:
        return None
    return items[-1]
