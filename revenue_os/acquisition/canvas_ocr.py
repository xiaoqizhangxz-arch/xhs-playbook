"""
canvas_ocr.py
将含有 canvas 图表的页面打印为大尺寸 PDF，然后用 Claude Vision OCR 提取所有数字和文本。

策略（与 creator_capture.py 的 printToPDF 一致）：
  1. playwright headless 打开页面（复用 Chrome cookie）
  2. 等待图表渲染完毕（canvas > 0）
  3. 用 page.pdf(width=1920px, height=fullScrollHeight) 打印全页
  4. 用 gs（Ghostscript）将每页转为 PNG @ 150dpi
  5. 每张 PNG 发给 Claude claude-sonnet-4-6 Vision，提取结构化 JSON
  6. 合并结果写入 raw_data/creator_auto/<subdir>/<date>_ocr.json

支持的 surface（所有 capture_mode == "pdf_ocr"）：
  - creator_stats_overview  → 观看来源分布/CTR/完播率趋势
  - creator_stats_fans      → 涨粉趋势/粉丝画像
  - creator_stats_content   → 帖子数据表

用法：
  python canvas_ocr.py --surface creator_stats_fans [--date-from 2026-01-01 --date-to 2026-03-28]
  python canvas_ocr.py --all-stats        # 全部 stats surfaces
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

# ── path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SCRIPT_DIR.parent.parent  # revenue_os/scripts/
sys.path.insert(0, str(_SRC_DIR))

from revenue_os.acquisition.creator_catalog import (
    CREATOR_SURFACES, CreatorSurfaceSpec, get_creator_surface,
)
from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RUNTIME_ROOT
from revenue_os.foundation.ids import short_hash
from revenue_os.foundation.time_utils import utc_now_iso

TOOLING_ROOT = RUNTIME_ROOT / ".tooling" / "creator_capture"
NODE_ROOT = TOOLING_ROOT / "node"
PYTHON_VENV_ROOT = TOOLING_ROOT / "py"


# ── Playwright cookie helper (reuse from creator_capture) ────────────────────
def _python_bin() -> Path:
    return PYTHON_VENV_ROOT / "venv" / "bin" / "python"


def _dump_chrome_cookies(output_path: Path) -> None:
    python_bin = _python_bin()
    script = """
import json, os, browser_cookie3
from pathlib import Path
cookies = []
for c in browser_cookie3.chrome(domain_name='xiaohongshu.com'):
    cookies.append({
        'name': c.name, 'value': c.value, 'domain': c.domain,
        'path': c.path or '/', 'expires': float(c.expires) if c.expires else -1,
        'httpOnly': bool((getattr(c, '_rest', {}) or {}).get('HttpOnly')),
        'secure': bool(c.secure), 'sameSite': 'Lax',
    })
Path(os.environ['OUTPUT_PATH']).write_text(json.dumps(cookies), encoding='utf-8')
"""
    subprocess.run([str(python_bin), "-c", script],
                   check=True, env={**os.environ, "OUTPUT_PATH": str(output_path)})


# ── Playwright PDF printer ────────────────────────────────────────────────────
_PRINTER_SCRIPT = """
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');

(async () => {
  const url = process.env.TARGET_URL;
  const outputPdf = process.env.OUTPUT_PDF;
  const dateFrom = process.env.DATE_FROM;
  const dateTo = process.env.DATE_TO;
  const cookies = JSON.parse(fs.readFileSync(process.env.COOKIES_JSON, 'utf-8'));

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await context.addCookies(cookies);
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
  } catch (e) {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  }
  await page.waitForTimeout(3000);

  // Try to set date range if provided
  if (dateFrom && dateTo) {
    try {
      // Look for date picker and set range
      const dateInputs = await page.locator('input[placeholder*="日期"], input[placeholder*="开始"], .date-picker input').all();
      if (dateInputs.length >= 2) {
        await dateInputs[0].fill(dateFrom);
        await page.keyboard.press('Tab');
        await dateInputs[1].fill(dateTo);
        await page.keyboard.press('Enter');
        await page.waitForTimeout(2000);
      }
    } catch (e) { /* date setting optional */ }
  }

  // Wait for canvas charts to render
  let canvasCount = 0;
  for (let i = 0; i < 10; i++) {
    canvasCount = await page.evaluate(() =>
      document.querySelectorAll('canvas').length
    );
    if (canvasCount > 0) break;
    await page.waitForTimeout(1000);
  }

  // Scroll through page to trigger lazy loads
  const totalHeight = await page.evaluate(() => document.body.scrollHeight);
  for (let pos = 0; pos < totalHeight; pos += 800) {
    await page.evaluate((y) => window.scrollTo(0, y), pos);
    await page.waitForTimeout(300);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1500);

  // Print full-page PDF
  const fullHeight = await page.evaluate(() =>
    Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 1080)
  );
  const paperHeight = Math.min(30000, fullHeight + 240);

  await page.pdf({
    path: outputPdf,
    printBackground: true,
    preferCSSPageSize: false,
    width: '1920px',
    height: `${paperHeight}px`,
    margin: { top: '16px', right: '16px', bottom: '16px', left: '16px' },
  });

  const result = {
    url: page.url(),
    title: await page.title(),
    canvas_count: canvasCount,
    paper_height: paperHeight,
    captured_at: new Date().toISOString(),
  };
  fs.writeFileSync(process.env.OUTPUT_META, JSON.stringify(result), 'utf-8');
  await browser.close();
})();
"""


def _print_to_pdf(surface: CreatorSurfaceSpec, output_pdf: Path,
                  date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Navigate to surface URL with Chrome cookies and print full-page PDF."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cookies_path = tmp / "cookies.json"
        meta_path = tmp / "meta.json"
        script_path = tmp / "printer.js"

        _dump_chrome_cookies(cookies_path)
        script_path.write_text(_PRINTER_SCRIPT, encoding="utf-8")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "COOKIES_JSON": str(cookies_path),
            "OUTPUT_PDF": str(output_pdf),
            "OUTPUT_META": str(meta_path),
            "TARGET_URL": surface.route_url,
            "DATE_FROM": date_from or "",
            "DATE_TO": date_to or "",
            "PLAYWRIGHT_MODULE": str(NODE_ROOT / "node_modules" / "@playwright" / "test"),
            "PLAYWRIGHT_CHANNEL": os.environ.get("REVENUE_OS_PLAYWRIGHT_CHANNEL", ""),
        }
        result = subprocess.run(
            ["node", str(script_path)],
            cwd=NODE_ROOT, env=env,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PDF print failed for {surface.name}: {result.stderr[-800:]}")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        meta["pdf_path"] = str(output_pdf)
        return meta


# ── PDF → PNG pages ───────────────────────────────────────────────────────────
def _pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    """Convert each PDF page to a PNG using ghostscript."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "page_%03d.png")
    result = subprocess.run(
        ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
         f"-r{dpi}", f"-sOutputFile={pattern}", str(pdf_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript failed: {result.stderr[-400:]}")
    pages = sorted(out_dir.glob("page_*.png"))
    return pages


# ── Claude Vision OCR ─────────────────────────────────────────────────────────
_OCR_PROMPT = """这是小红书创作者后台的数据截图。
请提取所有可见的数据，以结构化 JSON 返回。
要求：
1. 提取所有图表标题
2. 提取所有数字指标（名称 + 数值 + 单位 + 时间范围）
3. 对于分布图（饼图/柱状图），提取每个分类的名称和占比/数值
4. 对于趋势图（折线图），提取关键节点数值（最高/最低/最新）
5. 提取所有可见的文字标签和图例

返回格式：
{
  "page_title": "...",
  "time_range": "...",
  "metrics": [{"name": "...", "value": "...", "unit": "...", "context": "..."}],
  "charts": [{"title": "...", "type": "...", "data": [...]}],
  "raw_text": "完整文字提取..."
}"""


def _ocr_png_with_claude(png_path: Path) -> dict[str, Any]:
    """Send PNG to Claude Vision and extract structured data."""
    try:
        import anthropic
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "anthropic"],
                      check=True, stdout=subprocess.DEVNULL)
        import anthropic  # type: ignore

    img_data = base64.b64encode(png_path.read_bytes()).decode()

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_data}},
                {"type": "text", "text": _OCR_PROMPT},
            ],
        }],
    )
    text = resp.content[0].text if resp.content else ""
    # Try to parse JSON from response
    try:
        # Find JSON block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return {"raw_text": text, "parse_error": "could not extract JSON"}


# ── Main OCR pipeline ─────────────────────────────────────────────────────────
def run_canvas_ocr(
    surface_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    dpi: int = 150,
) -> dict[str, Any]:
    """Full pipeline: navigate → PDF → PNG pages → OCR each page → save JSON."""
    surface = get_creator_surface(surface_name)
    today = date.today().isoformat()
    date_from = date_from or today
    date_to = date_to or today

    out_dir = CREATOR_AUTO_ROOT / surface.route_subdir
    digest = short_hash([surface_name, date_from, date_to, utc_now_iso()])
    pdf_path = out_dir / f"{surface_name}__{digest}.pdf"
    ocr_out = out_dir / f"{surface_name}__{digest}_ocr.json"

    print(f"  📸 打印 PDF: {surface.source_url}")
    meta = _print_to_pdf(surface, pdf_path, date_from, date_to)
    print(f"     canvas_count={meta.get('canvas_count', '?')}  height={meta.get('paper_height', '?')}px")

    with tempfile.TemporaryDirectory() as tmpdir:
        png_dir = Path(tmpdir) / "pages"
        print(f"  🖼  转换为 PNG @ {dpi}dpi...")
        pages = _pdf_to_pngs(pdf_path, png_dir, dpi)
        print(f"     {len(pages)} 页")

        ocr_results = []
        for i, page in enumerate(pages):
            print(f"  🔍 OCR 第 {i+1}/{len(pages)} 页...")
            result = _ocr_png_with_claude(page)
            result["page_index"] = i + 1
            result["png_size_kb"] = page.stat().st_size // 1024
            ocr_results.append(result)
            time.sleep(0.5)  # rate limit

    output = {
        "surface": surface_name,
        "source_url": surface.source_url,
        "date_from": date_from,
        "date_to": date_to,
        "captured_at": utc_now_iso(),
        "pdf_path": str(pdf_path),
        "page_count": len(pages),
        "canvas_count": meta.get("canvas_count", 0),
        "pages": ocr_results,
    }
    ocr_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ OCR 结果: {ocr_out.name}")
    return output


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canvas PDF→OCR pipeline")
    parser.add_argument("--surface", help="Surface name (e.g. creator_stats_fans)")
    parser.add_argument("--all-stats", action="store_true", help="Run all pdf_ocr surfaces")
    parser.add_argument("--date-from", help="Date from YYYY-MM-DD")
    parser.add_argument("--date-to", help="Date to YYYY-MM-DD")
    parser.add_argument("--dpi", type=int, default=150, help="PNG resolution (default 150)")
    args = parser.parse_args()

    targets = []
    if args.all_stats:
        targets = [s.name for s in CREATOR_SURFACES if s.capture_mode == "pdf_ocr"]
    elif args.surface:
        targets = [args.surface]
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Canvas OCR Pipeline  {args.date_from or 'today'} → {args.date_to or 'today'}")
    print(f"Surfaces: {', '.join(targets)}")
    print(f"{'='*60}\n")

    for surface_name in targets:
        print(f"\n▶ {surface_name}")
        try:
            result = run_canvas_ocr(
                surface_name=surface_name,
                date_from=args.date_from,
                date_to=args.date_to,
                dpi=args.dpi,
            )
            pages = result.get("pages", [])
            metrics_count = sum(len(p.get("metrics", [])) for p in pages)
            print(f"  → {len(pages)} pages, {metrics_count} metrics extracted")
        except Exception as e:
            print(f"  ❌ {e}")
