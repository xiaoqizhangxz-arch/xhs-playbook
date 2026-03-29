from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from revenue_os.acquisition.creator_capture import NODE_ROOT, _dump_chrome_cookies, _ensure_node_tooling
from revenue_os.acquisition.creator_catalog import CREATOR_HOME_URL, CREATOR_SURFACES
from revenue_os.acquisition.surface_catalog import ARK_HOME_URL, SURFACES
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


TIMEFRAME_PATTERNS = [
    "实时",
    "近1日",
    "近7日",
    "近30日",
    "最近1天",
    "最近7天",
    "最近30天",
    "自然月",
    "本月",
    "当月",
    "MTD",
]

NAV_KEYWORDS = [
    "经营",
    "成交",
    "流量",
    "店铺",
    "搜索",
    "商品",
    "售后",
    "退款",
    "订单",
    "物流",
    "结算",
    "资金",
    "用户",
    "人群",
    "资产",
    "分析",
    "趋势",
    "粉丝",
    "笔记",
    "活动",
    "灵感",
    "创作",
]


def _default_seed_url(source_system: str) -> str:
    if source_system == "qianfan":
        return ARK_HOME_URL
    if source_system == "creator":
        return CREATOR_HOME_URL
    raise ValueError(f"Unsupported source_system: {source_system}")


def _catalog_urls(source_system: str) -> list[str]:
    if source_system == "qianfan":
        return sorted({surface.source_url for surface in SURFACES})
    if source_system == "creator":
        return sorted({surface.source_url for surface in CREATOR_SURFACES})
    raise ValueError(f"Unsupported source_system: {source_system}")


def _known_labels(source_system: str) -> set[str]:
    labels: set[str] = set()
    if source_system == "qianfan":
        for surface in SURFACES:
            labels.add(str(surface.name))
            labels.add(str(surface.navigation_hint))
            labels.add(str(surface.route_subdir))
    elif source_system == "creator":
        for surface in CREATOR_SURFACES:
            labels.add(str(surface.name))
            labels.add(str(surface.navigation_hint))
            labels.add(str(surface.route_subdir))
    return {item for item in labels if item}


def _norm_text(value: str) -> str:
    token = value.lower()
    parts = re.findall(r"[a-z0-9\u4e00-\u9fff]+", token)
    return "".join(parts)


def _write_discovery_script(
    script_path: Path,
    *,
    source_system: str,
    seed_url: str,
    max_pages: int,
    max_depth: int,
) -> None:
    payload = {
        "source_system": source_system,
        "seed_url": seed_url,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "patterns": TIMEFRAME_PATTERNS,
        "nav_keywords": NAV_KEYWORDS,
    }
    script = f"""
const {{ chromium }} = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');

(async () => {{
  const cfg = {json.dumps(payload, ensure_ascii=False)};
  const cookies = JSON.parse(fs.readFileSync(process.env.COOKIES_JSON, 'utf-8'));
  const launchOptions = {{ headless: true }};
  if (process.env.PLAYWRIGHT_CHANNEL) launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext();
  await context.addCookies(cookies);
  const page = await context.newPage();

  const host = new URL(cfg.seed_url).host;
  const queue = [{{ url: cfg.seed_url, depth: 0 }}];
  const visited = new Set();
  const discovered = new Set();
  const pages = [];
  const apiEndpoints = new Map();
  const clickLabels = new Set();
  const pageErrors = [];

  const normalize = (raw) => {{
    try {{
      const u = new URL(raw, cfg.seed_url);
      if (!u.host.includes('xiaohongshu.com')) return null;
      u.hash = '';
      return u.toString();
    }} catch (e) {{
      return null;
    }}
  }};

  const textCompact = (value) => (value || '').replace(/\\s+/g, ' ').trim();

  page.on('request', (req) => {{
    try {{
      const raw = req.url();
      const u = new URL(raw);
      if (!u.host.includes('xiaohongshu.com')) return;
      const endpoint = `${{u.origin}}${{u.pathname}}`;
      if (!/(api|fe_api|galaxy|datacenter|business|seller|creator|ark)/i.test(endpoint)) return;
      apiEndpoints.set(endpoint, (apiEndpoints.get(endpoint) || 0) + 1);
    }} catch (e) {{}}
  }});

  page.on('pageerror', (err) => {{
    pageErrors.push(String(err || '').slice(0, 500));
  }});

  while (queue.length && visited.size < cfg.max_pages) {{
    const item = queue.shift();
    if (!item || visited.has(item.url)) continue;
    visited.add(item.url);

    let title = '';
    let bodyText = '';
    let links = [];
    let timeframeHits = [];
    let labels = [];

    try {{
      await page.goto(item.url, {{ waitUntil: 'domcontentloaded', timeout: 45000 }});
      await page.waitForTimeout(2000);
      title = await page.title();
      bodyText = await page.locator('body').innerText();
      links = await page.evaluate(() => {{
        return Array.from(document.querySelectorAll('a[href]')).slice(0, 1200).map((a) => {{
          return {{
            href: a.getAttribute('href') || '',
            text: textCompact(a.innerText || a.textContent || '').slice(0, 140),
          }};
        }});
      }});
      timeframeHits = await page.evaluate((patterns) => {{
        const nodes = Array.from(document.querySelectorAll('button,[role=\"tab\"],[class*=\"tab\"],[class*=\"filter\"],[class*=\"date\"]')).slice(0, 2000);
        const out = [];
        for (const n of nodes) {{
          const t = textCompact(n.innerText || n.textContent || '').slice(0, 140);
          if (!t) continue;
          if (patterns.some((p) => t.includes(p))) out.push(t);
        }}
        return Array.from(new Set(out)).slice(0, 120);
      }}, cfg.patterns);
      labels = await page.evaluate((keywords) => {{
        const nodes = Array.from(document.querySelectorAll('button,[role=\"tab\"],[role=\"menuitem\"],a,[class*=\"menu\"],[class*=\"nav\"],[class*=\"tab\"],[class*=\"item\"]')).slice(0, 3500);
        const out = [];
        for (const n of nodes) {{
          const t = textCompact(n.innerText || n.textContent || '').slice(0, 120);
          if (!t) continue;
          if (!/[\\u4e00-\\u9fffA-Za-z0-9]/.test(t)) continue;
          if (!keywords.some((k) => t.includes(k))) continue;
          out.push(t);
        }}
        return Array.from(new Set(out)).slice(0, 300);
      }}, cfg.nav_keywords);
      for (const label of labels) clickLabels.add(label);
    }} catch (e) {{
      pages.push({{
        url: item.url,
        depth: item.depth,
        title,
        error: String(e),
        timeframe_hits: [],
        click_labels: [],
        link_count: 0
      }});
      continue;
    }}

    const normalized = [];
    for (const link of links) {{
      const n = normalize(link.href);
      if (!n) continue;
      normalized.push({{ url: n, text: link.text }});
      discovered.add(n);
    }}

    if (item.depth < cfg.max_depth) {{
      for (const link of normalized) {{
        if (!visited.has(link.url) && !queue.find((q) => q.url === link.url)) {{
          queue.push({{ url: link.url, depth: item.depth + 1 }});
        }}
      }}
    }}

    pages.push({{
      url: item.url,
      depth: item.depth,
      title,
      timeframe_hits: timeframeHits,
      click_labels: labels.slice(0, 80),
      link_count: normalized.length,
      sample_links: normalized.slice(0, 30),
      body_preview: (bodyText || '').slice(0, 500),
    }});
  }}

  const payloadOut = {{
    captured_at: new Date().toISOString(),
    source_system: cfg.source_system,
    seed_url: cfg.seed_url,
    max_pages: cfg.max_pages,
    max_depth: cfg.max_depth,
    visited_page_count: visited.size,
    discovered_url_count: discovered.size,
    discovered_urls: Array.from(discovered).sort(),
    discovered_api_endpoints: Array.from(apiEndpoints.entries()).sort((a, b) => b[1] - a[1]).map((it) => it[0]).slice(0, 500),
    discovered_click_labels: Array.from(clickLabels).sort(),
    api_request_count: Array.from(apiEndpoints.values()).reduce((acc, v) => acc + v, 0),
    page_error_count: pageErrors.length,
    page_errors: pageErrors.slice(0, 120),
    page_summaries: pages,
    patterns: cfg.patterns,
  }};
  fs.writeFileSync(process.env.OUTPUT_JSON, JSON.stringify(payloadOut, null, 2), 'utf-8');
  await browser.close();
}})();
"""
    script_path.write_text(script, encoding="utf-8")


def run_interface_discovery(
    *,
    source_system: str = "qianfan",
    browser_name: str = "chrome",
    seed_url: str | None = None,
    max_pages: int = 120,
    max_depth: int = 2,
) -> dict[str, Any]:
    if source_system not in {"qianfan", "creator"}:
        raise ValueError(f"Unsupported source_system: {source_system}")
    if browser_name != "chrome":
        raise ValueError("interface discovery currently supports chrome only")

    seed = seed_url or _default_seed_url(source_system)
    _ensure_node_tooling()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        cookies_json = tmp_root / "cookies.json"
        output_json = tmp_root / "discovery.json"
        script_path = tmp_root / "interface_discovery.js"

        _dump_chrome_cookies(cookies_json, browser_name)
        _write_discovery_script(
            script_path,
            source_system=source_system,
            seed_url=seed,
            max_pages=max_pages,
            max_depth=max_depth,
        )

        env = {
            **os.environ,
            "COOKIES_JSON": str(cookies_json),
            "OUTPUT_JSON": str(output_json),
            "PLAYWRIGHT_MODULE": str(NODE_ROOT / "node_modules" / "@playwright" / "test"),
            "PLAYWRIGHT_CHANNEL": os.environ.get("REVENUE_OS_PLAYWRIGHT_CHANNEL", ""),
        }

        completed = subprocess.run(
            ["node", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"interface discovery failed: source={source_system} exit={completed.returncode}; "
                f"stderr={(completed.stderr or '')[-1200:]}"
            )
        raw = json.loads(output_json.read_text(encoding="utf-8"))

    catalog_urls = _catalog_urls(source_system)
    discovered_urls = list(raw.get("discovered_urls", []))
    if source_system == "qianfan":
        missing_from_catalog = sorted([url for url in discovered_urls if "/app-" in url and url not in catalog_urls])
    else:
        missing_from_catalog = sorted([url for url in discovered_urls if "/new/" in url and url not in catalog_urls])

    timeframe_hits: dict[str, int] = {}
    for page in raw.get("page_summaries", []):
        for token in page.get("timeframe_hits", []):
            timeframe_hits[token] = int(timeframe_hits.get(token, 0) or 0) + 1

    known_labels = _known_labels(source_system)
    known_tokens = {_norm_text(item) for item in known_labels if item}
    discovered_click_labels = [str(item) for item in raw.get("discovered_click_labels", []) if item]
    unknown_click_labels: list[str] = []
    for label in discovered_click_labels:
        token = _norm_text(label)
        if not token:
            continue
        if any(known in token or token in known for known in known_tokens):
            continue
        unknown_click_labels.append(label)

    report = {
        "schema_version": "1.0.0",
        "object_type": "qianfan_discovery_report",
        "report_id": deterministic_id("discover", source_system, seed, utc_now_iso()),
        "source_system": source_system,
        "created_at": utc_now_iso(),
        "seed_url": seed,
        "browser_name": browser_name,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "visited_page_count": int(raw.get("visited_page_count", 0) or 0),
        "discovered_url_count": int(raw.get("discovered_url_count", 0) or 0),
        "catalog_url_count": len(catalog_urls),
        "catalog_urls": catalog_urls,
        "discovered_urls": discovered_urls,
        "missing_from_catalog_urls": missing_from_catalog,
        "discovered_api_endpoints": [str(item) for item in raw.get("discovered_api_endpoints", [])],
        "api_request_count": int(raw.get("api_request_count", 0) or 0),
        "discovered_click_labels": discovered_click_labels,
        "missing_from_catalog_click_labels": sorted(set(unknown_click_labels)),
        "page_error_count": int(raw.get("page_error_count", 0) or 0),
        "timeframe_hits": timeframe_hits,
        "page_summaries": raw.get("page_summaries", []),
        "source_of_truth": "live xiaohongshu navigation + network discovery with browser-context cookies",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("qianfan_discovery_report", report)
    return report


def run_qianfan_discovery(
    *,
    browser_name: str = "chrome",
    seed_url: str = ARK_HOME_URL,
    max_pages: int = 120,
    max_depth: int = 2,
) -> dict[str, Any]:
    return run_interface_discovery(
        source_system="qianfan",
        browser_name=browser_name,
        seed_url=seed_url,
        max_pages=max_pages,
        max_depth=max_depth,
    )
