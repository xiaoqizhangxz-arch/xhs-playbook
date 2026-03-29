"""
canvas_ocr.py
将含有 canvas 图表的 creator 页面打印为大尺寸 PDF，然后用 OCR 提取所有数字和文本。

策略（与 creator_capture.py 的 printToPDF 一致）：
  1. playwright headless 打开页面（复用 Chrome cookie）
  2. 点击目标时间 tab（近7天/近30天等）
  3. 等待 canvas 图表渲染
  4. 用 page.pdf(width=1920px, height=fullScrollHeight) 打印全页
  5. 用 gs（Ghostscript）将每页转为 PNG @ 150dpi
  6. OCR：优先 Tesseract（本地，免费）→ 回退 Claude Vision
  7. 合并结果写入 raw_data/creator_auto/<subdir>/<date>_ocr.json

已确认可用的 creator statistics 页面（2026-03-28 探测）：
  ┌──────────────────────────────────────────────────────────────┐
  │ URL                                              canvas tab  │
  │ /statistics/account/v2    账号概览               4     近7/30日 │
  │ /statistics/fans-data     粉丝数据/画像          5     近7/30天 │
  │ /statistics/data-analysis 内容分析(笔记列表)     0     日期过滤 │
  └──────────────────────────────────────────────────────────────┘

注意：/statistics/data-analysis 是表格不是图表，用 DOM 文字即可，不需要 OCR。

用法：
  python canvas_ocr.py --surface creator_stats_fans [--window 30]
  python canvas_ocr.py --all-stats
  python canvas_ocr.py --surface creator_stats_fans --window 7
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
from datetime import date
from pathlib import Path
from typing import Any

# ── path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_SRC_DIR))

from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RUNTIME_ROOT
from revenue_os.foundation.ids import short_hash
from revenue_os.foundation.time_utils import utc_now_iso

TOOLING_ROOT = RUNTIME_ROOT / ".tooling" / "creator_capture"
NODE_ROOT = TOOLING_ROOT / "node"
PYTHON_VENV_ROOT = TOOLING_ROOT / "py"

# ── Surface definitions ───────────────────────────────────────────────────────
# 2026-03-28 探测确认：这些页面有 canvas 图表，支持时间 tab
STATS_SURFACES = {
    "creator_stats_account": {
        "url": "https://creator.xiaohongshu.com/statistics/account/v2",
        "label": "账号概览",
        "subdir": "stats_account",
        "canvas_count": 4,
        "time_tabs": {"7": "近7日", "30": "近30日"},
        "default_window": "30",
        "notes": "曝光/观看/互动/涨粉趋势 canvas 图表",
    },
    "creator_stats_fans": {
        "url": "https://creator.xiaohongshu.com/statistics/fans-data",
        "label": "粉丝数据/画像",
        "subdir": "stats_fans",
        "canvas_count": 5,
        "time_tabs": {"7": "近7天", "30": "近30天"},
        "default_window": "30",
        "notes": "粉丝数趋势+粉丝画像(性别/年龄/兴趣/地域) canvas 图表",
    },
    # data-analysis 是笔记表格，不是图表，用 DOM 文字采集
    # 放这里只是为了完整性，capture_mode='dom'
    "creator_stats_content": {
        "url": "https://creator.xiaohongshu.com/statistics/data-analysis",
        "label": "内容分析（笔记表格）",
        "subdir": "stats_content",
        "canvas_count": 0,
        "time_tabs": {},
        "default_window": "dom",  # 不需要 canvas OCR
        "notes": "笔记列表表格，DOM 文字即可，无 canvas 图表",
    },
}


# ── Cookie helper ─────────────────────────────────────────────────────────────
def _dump_chrome_cookies(output_path: Path) -> None:
    python_bin = PYTHON_VENV_ROOT / "venv" / "bin" / "python"
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
    subprocess.run([str(python_bin), "-c", script], check=True,
                   env={**os.environ, "OUTPUT_PATH": str(output_path)})


# ── Playwright PDF printer ────────────────────────────────────────────────────
_PRINTER_JS = """\
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');
(async () => {
  const cfg = JSON.parse(process.env.CAPTURE_CONFIG);
  const cookies = JSON.parse(fs.readFileSync(process.env.COOKIES_JSON, 'utf-8'));
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await ctx.addCookies(cookies);
  const page = await ctx.newPage();

  try {
    await page.goto(cfg.url, { waitUntil: 'networkidle', timeout: 45000 });
  } catch(e) {
    await page.goto(cfg.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  }
  await page.waitForTimeout(3000);

  // Click time tab if specified
  if (cfg.timeTab) {
    const btn = page.getByText(cfg.timeTab, { exact: true });
    if (await btn.count() > 0) {
      await btn.first().click({ timeout: 5000 });
      await page.waitForTimeout(2000);
    }
  }

  // Wait for canvas charts to render (up to 10s)
  let canvasCount = 0;
  for (let i = 0; i < 10; i++) {
    canvasCount = await page.evaluate(() => document.querySelectorAll('canvas').length);
    if (canvasCount > 0) break;
    await page.waitForTimeout(1000);
  }

  // Scroll through to trigger lazy load
  const totalH = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < totalH; y += 600) {
    await page.evaluate((pos) => window.scrollTo(0, pos), y);
    await page.waitForTimeout(200);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1500);

  // Full-page PDF
  const fullH = await page.evaluate(() =>
    Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 1080)
  );
  const paperH = Math.min(30000, fullH + 240);
  await page.pdf({
    path: process.env.OUTPUT_PDF,
    printBackground: true,
    preferCSSPageSize: false,
    width: '1920px',
    height: `${paperH}px`,
    margin: { top: '16px', right: '16px', bottom: '16px', left: '16px' },
  });

  // Also grab body text (table / DOM data)
  const bodyText = await page.evaluate(() => document.body.innerText);

  const result = {
    url: page.url(), title: await page.title(),
    canvas_count: canvasCount, paper_height: paperH,
    body_text: bodyText,
    captured_at: new Date().toISOString(),
  };
  fs.writeFileSync(process.env.OUTPUT_META, JSON.stringify(result), 'utf-8');
  await browser.close();
})();
"""


def _print_to_pdf(surface_cfg: dict, output_pdf: Path, window: str) -> dict[str, Any]:
    """Navigate + click time tab + print full-page PDF."""
    time_tabs = surface_cfg.get("time_tabs", {})
    time_tab_text = time_tabs.get(window) or time_tabs.get(surface_cfg.get("default_window", ""))
    capture_config = json.dumps({
        "url": surface_cfg["url"],
        "timeTab": time_tab_text or "",
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cookies_path = tmp / "cookies.json"
        meta_path = tmp / "meta.json"
        script_path = tmp / "printer.js"

        _dump_chrome_cookies(cookies_path)
        script_path.write_text(_PRINTER_JS, encoding="utf-8")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "COOKIES_JSON": str(cookies_path),
            "OUTPUT_PDF": str(output_pdf),
            "OUTPUT_META": str(meta_path),
            "CAPTURE_CONFIG": capture_config,
            "PLAYWRIGHT_MODULE": str(NODE_ROOT / "node_modules" / "@playwright" / "test"),
            "PLAYWRIGHT_CHANNEL": os.environ.get("REVENUE_OS_PLAYWRIGHT_CHANNEL", ""),
        }
        result = subprocess.run(["node", str(script_path)], cwd=NODE_ROOT, env=env,
                                 capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"PDF print failed: {result.stderr[-600:]}")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        meta["pdf_path"] = str(output_pdf)
        return meta


# ── PDF → PNG ─────────────────────────────────────────────────────────────────
def _pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "page_%03d.png")
    result = subprocess.run(
        ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", f"-r{dpi}",
         f"-sOutputFile={pattern}", str(pdf_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript failed: {result.stderr[-300:]}")
    return sorted(out_dir.glob("page_*.png"))


# ── OCR backends ──────────────────────────────────────────────────────────────

_OCR_PROMPT = (
    "提取这张截图里所有可见的数据。返回JSON格式：\n"
    '{"page_title":"","time_range":"","metrics":[{"name":"","value":"","unit":""}],'
    '"charts":[{"title":"","type":"pie|bar|line|table","data":[{"label":"","value":""}]}],'
    '"raw_text":"完整文字提取"}'
    "\n只返回JSON，不要其他文字。"
)


def _ocr_tesseract(png_path: Path) -> dict[str, Any]:
    """
    Tesseract OCR (local, free).
    适合：纯文字/表格页面。
    不适合：canvas 渲染图表（反锯齿字体，识别率低）。
    Install: brew install tesseract tesseract-lang  (chi_sim 已确认可用)
    """
    result = subprocess.run(
        ["tesseract", str(png_path), "stdout", "-l", "chi_sim+eng", "--psm", "6"],
        capture_output=True, text=True, timeout=60,
    )
    text = result.stdout.strip()
    return {"backend": "tesseract", "raw_text": text,
            "lines": [l for l in text.splitlines() if l.strip()]}


def _ocr_gemini_api(png_path: Path) -> dict[str, Any]:
    """
    Gemini Vision OCR via google-generativeai SDK.
    Model: gemini-2.0-flash（极低成本，有 free tier）。
    主力 OCR backend，专为 canvas 图表设计。
    需要: pip install google-generativeai
          环境变量: GEMINI_API_KEY 或 GOOGLE_API_KEY
    """
    try:
        import google.generativeai as genai
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "google-generativeai", "-q"],
            check=True,
        )
        import google.generativeai as genai  # type: ignore

    api_key = (os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY")
               or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    import PIL.Image
    img = PIL.Image.open(png_path)
    resp = model.generate_content([_OCR_PROMPT, img])
    text = resp.text if resp.text else ""
    try:
        start = text.find("{"); end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            result["backend"] = "gemini-2.0-flash"
            return result
    except json.JSONDecodeError:
        pass
    return {"backend": "gemini-2.0-flash", "raw_text": text}


def _ocr_claude_fallback(png_path: Path) -> dict[str, Any]:
    """
    Claude Haiku Vision OCR — 最后 fallback。
    只在 gemini 不可用时使用。
    """
    try:
        import anthropic
    except ImportError:
        return {"backend": "unavailable", "raw_text": ""}
    img_b64 = base64.b64encode(png_path.read_bytes()).decode()
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
            {"type": "text", "text": _OCR_PROMPT},
        ]}],
    )
    text = resp.content[0].text if resp.content else ""
    try:
        start = text.find("{"); end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            result["backend"] = "claude_haiku"
            return result
    except json.JSONDecodeError:
        pass
    return {"backend": "claude_haiku", "raw_text": text}


def _ocr_page(png_path: Path, has_canvas: bool = True) -> dict[str, Any]:
    """
    OCR 策略（按优先级）：
      canvas 页面 → Gemini 2.0 Flash（最佳质量，低成本）→ Claude Haiku（fallback）
      纯文字/表格 → Tesseract（免费）→ Gemini Flash（fallback）
    """
    if not has_canvas:
        # 纯文字页，tesseract 效果好
        if subprocess.run(["which", "tesseract"], capture_output=True).returncode == 0:
            result = _ocr_tesseract(png_path)
            if result.get("raw_text") and len(result["raw_text"]) > 100:
                return result
        # tesseract 失败，用 gemini
        has_canvas = True  # fall through to gemini

    # canvas 图表页：gemini flash 主力
    gemini_key = (os.environ.get("GEMINI_API_KEY")
                  or os.environ.get("GOOGLE_API_KEY")
                  or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
    if gemini_key:
        try:
            return _ocr_gemini_api(png_path)
        except Exception as e:
            print(f"    ⚠️  Gemini OCR failed: {e}, falling back to Claude Haiku")

    # Final fallback: claude haiku
    return _ocr_claude_fallback(png_path)


# ── Main pipeline ─────────────────────────────────────────────────────────────
def run_canvas_ocr(
    surface_name: str,
    window: str = "30",
    dpi: int = 150,
) -> dict[str, Any]:
    """Full pipeline: navigate → click tab → PDF → PNG pages → OCR → save JSON."""
    if surface_name not in STATS_SURFACES:
        raise ValueError(f"Unknown surface: {surface_name}. Available: {list(STATS_SURFACES)}")

    surface_cfg = STATS_SURFACES[surface_name]
    if surface_cfg.get("default_window") == "dom":
        print(f"  ⚠️  {surface_name} 是 DOM 表格，不需要 canvas OCR。跳过。")
        return {"status": "skip_dom_only"}

    out_dir = CREATOR_AUTO_ROOT / surface_cfg["subdir"]
    today = date.today().isoformat()
    digest = short_hash([surface_name, window, today, utc_now_iso()])
    pdf_path = out_dir / f"{surface_name}_{today}_{digest[:8]}.pdf"
    ocr_out = out_dir / f"{surface_name}_{today}_{digest[:8]}_ocr.json"

    print(f"  📸 打印 PDF: {surface_cfg['url']}")
    meta = _print_to_pdf(surface_cfg, pdf_path, window)
    canvas_n = meta.get("canvas_count", 0)
    paper_h = meta.get("paper_height", "?")
    print(f"     canvas={canvas_n}  height={paper_h}px  tab=近{window}天/日")

    if canvas_n == 0:
        print(f"  ⚠️  canvas=0，页面可能未加载图表。保存 body_text 作为 DOM 降级。")

    ocr_pages = []
    with tempfile.TemporaryDirectory() as tmpdir:
        png_dir = Path(tmpdir) / "pages"
        print(f"  🖼  转换为 PNG @ {dpi}dpi...", end=" ", flush=True)
        pages = _pdf_to_pngs(pdf_path, png_dir, dpi)
        print(f"{len(pages)} 页")

        has_canvas = canvas_n > 0
        gemini_key = (os.environ.get("GEMINI_API_KEY")
                      or os.environ.get("GOOGLE_API_KEY")
                      or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        primary_backend = ("gemini-2.0-flash" if (has_canvas and gemini_key)
                           else "tesseract" if not has_canvas
                           else "claude_haiku")
        print(f"  🔍 OCR backend: {primary_backend} (canvas={has_canvas})")

        for i, page in enumerate(pages):
            print(f"  🔍 页 {i+1}/{len(pages)}...", end=" ", flush=True)
            result = _ocr_page(page, has_canvas=has_canvas)
            result["page_index"] = i + 1
            result["png_kb"] = page.stat().st_size // 1024
            ocr_pages.append(result)
            text_len = len(result.get("raw_text", ""))
            print(f"{text_len} chars [{result.get('backend','?')}]")
            time.sleep(0.3)

    output = {
        "surface": surface_name,
        "label": surface_cfg["label"],
        "source_url": surface_cfg["url"],
        "window": f"近{window}天/日",
        "captured_at": utc_now_iso(),
        "pdf_path": str(pdf_path),
        "page_count": len(ocr_pages),
        "canvas_count": canvas_n,
        "body_text_fallback": meta.get("body_text", "")[:3000],  # DOM fallback
        "pages": ocr_pages,
    }
    ocr_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ 结果: {ocr_out.name}")
    return output


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Creator canvas PDF→OCR")
    parser.add_argument("--surface", choices=list(STATS_SURFACES),
                        help="目标 surface")
    parser.add_argument("--all-stats", action="store_true",
                        help="运行所有有 canvas 的 stats surfaces")
    parser.add_argument("--window", default="30", choices=["7", "30", "90"],
                        help="时间窗口（天数），默认 30")
    parser.add_argument("--dpi", type=int, default=150, help="PNG 分辨率（默认 150）")
    parser.add_argument("--no-gemini", action="store_true",
                        help="跳过 Gemini，直接用 claude_haiku fallback")
    args = parser.parse_args()

    targets = []
    if args.all_stats:
        targets = [k for k, v in STATS_SURFACES.items() if v.get("canvas_count", 0) > 0]
    elif args.surface:
        targets = [args.surface]
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Canvas OCR  window=近{args.window}天/日  dpi={args.dpi}")
    print(f"Surfaces: {', '.join(targets)}")
    print(f"{'='*60}\n")

    for surface_name in targets:
        print(f"\n▶ {surface_name} ({STATS_SURFACES[surface_name]['label']})")
        try:
            result = run_canvas_ocr(
                surface_name=surface_name,
                window=args.window,
                dpi=args.dpi,
            )
            if result.get("status") == "skip_dom_only":
                continue
            pages = result.get("pages", [])
            chars = sum(len(p.get("raw_text", "")) for p in pages)
            print(f"  → {len(pages)} pages, ~{chars} chars total")
        except Exception as e:
            print(f"  ❌ {e}")
