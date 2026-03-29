"""
xhs_historical_collector.py — 千帆 ARK 历史数据全量采集

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法：
  python3 -m revenue_os.acquisition.xhs_historical_collector --start 2026-01-01 --end 2026-03-28
  python3 -m revenue_os.acquisition.xhs_historical_collector  # 默认: 2025-10-01 → 今天

时间控制：
  --start / --end  任意日期范围
  脚本自动按 ≤90天 切段（千帆"自定义"最大窗口为92天）

采集机制：
  1. 点击页面"自定义" tab
  2. 通过 HTMLInputElement.prototype.value setter 强制写入日期值
  3. 触发 input/change/blur 事件让 Vue 组件识别
  4. 等待3秒后读取 DOM 文字并保存

⚠️ 已知限制 - 跨月日期设置：
  千帆日历选择器在跨月时可能需要点击月份切换箭头。
  当前 JS setValue 方法有时被 Vue 虚拟 DOM 绕过（验证失败时
  打印 warning 并采集当前页数据）。
  → 待解决：补充月份导航逻辑（检测当前月 → 点箭头 → 选日期格子）

覆盖页面（23个，URL 探测日期 2026-03-28）：
  交易: 成交分析/账号分析/退款分析/订单明细/买手分析
  流量: 数据总览/流量数据
  商品: 商品总览/实时商品数据/商家类目
  搜索: 搜索总览/引流搜索词
  笔记: 笔记数据/买手笔记/笔记蓝链
  店铺: 店铺主页/评价数据/售后数据/物流数据/客服数据/群聊数据/买手清单
  市场: 市场行情

不在此脚本处理（由专门脚本负责）：
  人群分析/AINRL用户资产 → collect_user_pages.mjs（快照，无日期）
  Canvas 图表 → canvas_ocr.py（playwright PDF + Gemini OCR）
  XLSX 下载 → download_xlsx.mjs（点击下载按钮）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import argparse
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import REVENUE_OS_ROOT

# ── 路径 ────────────────────────────────────────────────────────────────────
HIST_DIR = REVENUE_OS_ROOT / "raw_data" / "creator_auto" / "historical"
HIST_DIR.mkdir(parents=True, exist_ok=True)

# ── Node.js daemon 脚本 ──────────────────────────────────────────────────────
_MJS = REVENUE_OS_ROOT / "scripts" / "revenue_os" / "acquisition" / "_daemon_exec.mjs"

def _ensure_mjs():
    _MJS.write_text(r'''
import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { writeFileSync } from 'fs';
const [,, action, ...args] = process.argv;
async function exec(tabId, code) { return sendCommand('exec', { code, tabId }); }
async function main() {
    if (action === 'navigate') {
        const nav = await sendCommand('navigate', { url: args[0], timeout: parseInt(args[1]||'500') });
        process.stdout.write(JSON.stringify(nav));
    } else if (action === 'exec') {
        const r = await exec(parseInt(args[0]), args.slice(1).join(' '));
        process.stdout.write(JSON.stringify({result: r}));
    } else if (action === 'screenshot') {
        const r = await sendCommand('screenshot', { tabId: parseInt(args[0]), format: 'png' });
        const raw = typeof r === 'string' ? r : r?.data;
        process.stdout.write(raw || '');
    } else if (action === 'canvas') {
        const code = `(function(){var cs=document.querySelectorAll('canvas');var o={};cs.forEach(function(c,i){if(c.width>100&&c.height>100){try{o['c'+i]={w:c.width,h:c.height,data:c.toDataURL('image/png')};}catch(e){}}});return JSON.stringify(o);})()`;
        const r = await exec(parseInt(args[0]), code);
        process.stdout.write(typeof r === 'string' ? r : JSON.stringify(r));
    }
}
main().catch(e => { process.stderr.write(e.message); process.exit(1); });
''', encoding='utf-8')

def _node(action: str, *args: str, timeout: int = 30) -> str:
    if not _MJS.exists():
        _ensure_mjs()
    r = subprocess.run(['node', str(_MJS), action, *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def _nav(url: str, wait: int = 500) -> dict:
    raw = _node('navigate', url, str(wait), timeout=20)
    try:
        return json.loads(raw)
    except Exception:
        return {}

def _exec(tab_id: int, code: str) -> str:
    raw = _node('exec', str(tab_id), code, timeout=20)
    try:
        return json.loads(raw).get('result', raw)
    except Exception:
        return raw

# ── 日期分段工具 ──────────────────────────────────────────────────────────────
def date_segments(start: date, end: date, max_days: int = 90) -> list[tuple[date, date]]:
    """把日期范围按 max_days 切割"""
    segments = []
    cur = start
    while cur <= end:
        seg_end = min(cur + timedelta(days=max_days - 1), end)
        segments.append((cur, seg_end))
        cur = seg_end + timedelta(days=1)
    return segments

# ── 千帆自定义日期设置（playwright headless，支持跨月）───────────────────────
# Node.js 脚本路径
_DATE_SETTER_JS = REVENUE_OS_ROOT / "scripts" / "revenue_os" / "acquisition" / "_ark_date_setter.js"

def _ensure_date_setter_mjs() -> None:
    """写出 headless playwright 日期设置脚本（首次调用时）"""
    if _DATE_SETTER_JS.exists():
        return
    script = r'''
/**
 * _ark_date_setter.mjs
 * playwright headless：在千帆 ARK 页面设置自定义日期范围
 * 用法: node _ark_date_setter.mjs <url> <start:YYYY-MM-DD> <end:YYYY-MM-DD>
 * 输出: JSON { ok, statsTime, expected }
 *
 * 通过月份箭头导航 + 点击日期格子，支持跨月设置
 */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');
const path = require('path');

const [,, pageUrl, startDate, endDate] = process.argv;
const [sy, sm, sd] = startDate.split('-').map(Number);
const [ey, em, ed] = endDate.split('-').map(Number);

const cookiesFile = process.env.COOKIES_JSON;
const cookies = JSON.parse(fs.readFileSync(cookiesFile, 'utf-8'));

async function getDisplayedMonths(page) {
    const texts = await page.evaluate(function(){
        return Array.from(document.querySelectorAll('.css-vmmof7'))
            .filter(function(el){ return el.getBoundingClientRect().height > 0; })
            .map(function(el){ return el.innerText.trim(); });
    });
    const months = [];
    for(let i = 0; i < texts.length - 1; i++) {
        const yM = texts[i].match(/(\d{4})/);
        const mM = texts[i+1].match(/(\d{1,2})/);
        if(yM && mM) months.push({ year: parseInt(yM[1]), month: parseInt(mM[1]) });
    }
    return months;
}

async function navigateToMonth(page, targetYear, targetMonth) {
    for(let a = 0; a < 36; a++) {
        const months = await getDisplayedMonths(page);
        if(!months.length) break;
        const left = months[0];
        const diff = (left.year - targetYear) * 12 + (left.month - targetMonth);
        if(diff === 0) return true;
        const svgs = await page.evaluate(function(){
            return Array.from(document.querySelectorAll('.css-7ll3nl')).map(function(svg){
                var r = svg.getBoundingClientRect();
                return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), cls: svg.className.baseVal };
            });
        });
        if(diff > 0) {
            const prev = svgs.find(function(s){ return s.cls.indexOf('css-cvpy5t') > -1; });
            if(prev) await page.mouse.click(prev.x, prev.y);
        } else {
            const next = svgs.find(function(s){ return s.cls.indexOf('css-fvvjfw') > -1; });
            if(next) await page.mouse.click(next.x, next.y);
        }
        await page.waitForTimeout(400);
    }
    return false;
}

async function clickDay(page, day, inLeft) {
    const cells = await page.evaluate(function(){
        return Array.from(document.querySelectorAll('.calendar-dayCell')).map(function(c){
            var r = c.getBoundingClientRect();
            return { text: c.innerText.trim(), x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), left: Math.round(r.x) };
        });
    });
    var allXs = cells.map(function(c){ return c.left; }).sort(function(a,b){ return a-b; });
    var midX = allXs[Math.floor(allXs.length/2)];
    var target = cells.find(function(c){
        return c.text === String(day) && (inLeft ? c.left < midX : c.left >= midX);
    });
    if(target) { await page.mouse.click(target.x, target.y); return true; }
    return false;
}

(async () => {
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
await ctx.addCookies(cookies);
const page = await ctx.newPage();

await page.goto(pageUrl, { waitUntil: 'networkidle', timeout: 45000 });
await page.waitForTimeout(3000);

// Click 自定义
await page.evaluate(function(){
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); var n;
    while(n = w.nextNode()){ if(n.textContent.trim() === '自定义' && n.parentElement.getBoundingClientRect().height > 0){ n.parentElement.click(); return; } }
});
await page.waitForTimeout(1200);
await page.locator("input[placeholder='开始时间']").first().click({ timeout: 5000 });
await page.waitForTimeout(1200);

const navOk = await navigateToMonth(page, sy, sm);
const r1 = await clickDay(page, sd, true);
await page.waitForTimeout(600);

const months = await getDisplayedMonths(page);
const endInLeft = months[0] && months[0].year === ey && months[0].month === em;
const endInRight = months[1] && months[1].year === ey && months[1].month === em;
if(!endInLeft && !endInRight) await navigateToMonth(page, ey, em > 1 ? em-1 : 12);
const months2 = await getDisplayedMonths(page);
const endLeft2 = months2[0] && months2[0].year === ey && months2[0].month === em;
const r2 = await clickDay(page, ed, endLeft2);
await page.waitForTimeout(2500);

const bodyText = await page.evaluate(function(){ return document.body.innerText; });
const m = bodyText.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
const statsTime = m ? m[0] : '';
const expected = startDate + '~' + endDate;

process.stdout.write(JSON.stringify({ ok: statsTime === expected, statsTime, expected, navOk, r1, r2 }));
await browser.close();
})();
'''
    _DATE_SETTER_JS.write_text(script.lstrip(), encoding='utf-8')


def _get_chrome_cookies_path() -> Path:
    """Dump Chrome cookies to a temp file, return path."""
    venv_python = REVENUE_OS_ROOT / "runtime" / "revenue_os" / ".tooling" / "creator_capture" / "py" / "venv" / "bin" / "python"
    cookies_path = Path(tempfile.mktemp(suffix='_cookies.json'))
    script = """
import json, os, browser_cookie3
from pathlib import Path
cookies = []
for c in browser_cookie3.chrome(domain_name='xiaohongshu.com'):
    cookies.append({'name': c.name, 'value': c.value, 'domain': c.domain,
        'path': c.path or '/', 'expires': float(c.expires) if c.expires else -1,
        'httpOnly': bool((getattr(c,'_rest',{}) or {}).get('HttpOnly')),
        'secure': bool(c.secure), 'sameSite': 'Lax'})
Path(os.environ['OUTPUT_PATH']).write_text(json.dumps(cookies))
"""
    subprocess.run([str(venv_python), '-c', script], check=True,
                   env={**os.environ, 'OUTPUT_PATH': str(cookies_path)})
    return cookies_path


_NODE_ROOT = REVENUE_OS_ROOT / "runtime" / "revenue_os" / ".tooling" / "creator_capture" / "node"
_PLAYWRIGHT_MODULE = _NODE_ROOT / "node_modules" / "@playwright" / "test"


def set_ark_date_range_playwright(page_url: str, start_str: str, end_str: str) -> bool:
    """
    Playwright headless 设置千帆 ARK 页面的自定义日期范围。
    通过月份箭头导航 + 点击日期格子实现，完全支持跨月。
    返回 True 表示设置成功并验证通过。
    """
    _ensure_date_setter_mjs()
    cookies_path = None
    try:
        cookies_path = _get_chrome_cookies_path()
        env = {
            **os.environ,
            'COOKIES_JSON': str(cookies_path),
            'PLAYWRIGHT_MODULE': str(_PLAYWRIGHT_MODULE),
            'PLAYWRIGHT_CHANNEL': '',
        }
        result = subprocess.run(
            ['node', str(_DATE_SETTER_JS), page_url, start_str, end_str],
            cwd=_NODE_ROOT, env=env,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"      ⚠️ playwright date setter error: {result.stderr[-200:]}")
            return False
        data = json.loads(result.stdout.strip() or '{}')
        if data.get('ok'):
            print(f"      ✅ 统计时间: {data.get('statsTime')}")
            return True
        else:
            print(f"      ⚠️ 日期验证失败: expected={data.get('expected')}, got={data.get('statsTime')}")
            return False
    except Exception as exc:
        print(f"      ⚠️ playwright date setter exception: {exc}")
        return False
    finally:
        if cookies_path and Path(cookies_path).exists():
            Path(cookies_path).unlink(missing_ok=True)


def set_ark_date_range(tab_id: int, start_str: str, end_str: str) -> bool:
    """
    设置千帆 ARK 页面自定义日期范围（向后兼容入口）。
    优先使用 playwright headless（支持跨月），回退到 browser bridge JS 注入。
    """
    # Get current page URL from browser bridge
    try:
        current_url = _exec(tab_id, 'location.href')
        if isinstance(current_url, str) and 'ark.xiaohongshu.com' in current_url:
            ok = set_ark_date_range_playwright(current_url, start_str, end_str)
            if ok:
                return True
            print(f"      ⚠️ playwright 失败，回退到 JS 注入方式")
    except Exception:
        pass

    # Fallback: JS setValue (may fail on cross-month)
    _exec(tab_id, """(function(){
        var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); var n;
        while(n=w.nextNode()){if(n.textContent.trim()==='自定义'){n.parentElement.click();return;}}
    })()""")
    time.sleep(1.5)
    _exec(tab_id, """(function(){
        var inp=document.querySelector('input[placeholder="开始时间"]');
        if(inp){inp.focus();inp.click();}
    })()""")
    time.sleep(1.5)
    set_code = f"""(function(){{
        var setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        var s=document.querySelector('input[placeholder="开始时间"]');
        var e=document.querySelector('input[placeholder="截止时间"]');
        if(s){{setter.call(s,'{start_str}');['input','change','blur'].forEach(function(ev){{s.dispatchEvent(new Event(ev,{{bubbles:true}}));}});}}
        if(e){{setter.call(e,'{end_str}');['input','change','blur'].forEach(function(ev){{e.dispatchEvent(new Event(ev,{{bubbles:true}}));}});}}
        return (s?s.value:'')+'|'+(e?e.value:'');
    }})()"""
    _exec(tab_id, set_code)
    time.sleep(1)
    body = _exec(tab_id, 'document.body.innerText')
    if not isinstance(body, str):
        body = str(body)
    return start_str in body or start_str.replace('-', '') in body

def collect_ark_page_snapshot(tab_id: int, path: str, label: str,
                               date_str: str) -> str | None:
    """采集无日期筛选页面的当前快照（如人群分析 /app-circle/user-data）"""
    print(f"    [{label}] snapshot {date_str}")

    current_url = _exec(tab_id, 'location.pathname')
    if path not in (current_url or ''):
        subprocess.run(['osascript', '-e',
            f'tell application "Google Chrome"\n'
            f'repeat with i from 1 to count of tabs of window 1\n'
            f'if URL of tab i of window 1 contains "ark.xiaohongshu.com" then\n'
            f'set URL of tab i of window 1 to "https://ark.xiaohongshu.com{path}"\n'
            f'exit repeat\nend if\nend repeat\nend tell'],
            capture_output=True, text=True)
        time.sleep(8)

    body = _exec(tab_id, 'document.body.innerText')
    text = body if isinstance(body, str) else str(body)

    if len(text) < 100:
        print(f"      ⚠️ 内容过短 ({len(text)} chars)")
        return None

    save_path = HIST_DIR / f"{date_str}_snapshot_{label}.txt"
    save_path.write_text(text, encoding='utf-8')
    print(f"      ✅ {len(text)} chars → {save_path.name}")
    return str(save_path)


def collect_ark_page_for_period(tab_id: int, path: str, label: str,
                                 start_str: str, end_str: str) -> str | None:
    """采集单个千帆页面的特定时间段数据"""
    print(f"    [{label}] {start_str}~{end_str}")

    # 导航到页面（如果不在该页面）
    current_url = _exec(tab_id, 'location.pathname')
    if path not in (current_url or ''):
        # 用 AppleScript 导航（保持 session）
        subprocess.run(['osascript', '-e',
            f'tell application "Google Chrome"\n'
            f'repeat with i from 1 to count of tabs of window 1\n'
            f'if URL of tab i of window 1 contains "ark.xiaohongshu.com" then\n'
            f'set URL of tab i of window 1 to "https://ark.xiaohongshu.com{path}"\n'
            f'exit repeat\nend if\nend repeat\nend tell'],
            capture_output=True, text=True)
        time.sleep(8)

    # 设置日期范围
    ok = set_ark_date_range(tab_id, start_str, end_str)
    if not ok:
        print(f"      ⚠️ 日期设置未确认，继续读取当前数据")
    time.sleep(3)

    # 读取 DOM
    body = _exec(tab_id, 'document.body.innerText')
    text = body if isinstance(body, str) else str(body)

    if len(text) < 200:
        print(f"      ⚠️ 内容过短 ({len(text)} chars)")
        return None

    # 保存
    save_path = HIST_DIR / f"{start_str}_{end_str}_{label}.txt"
    save_path.write_text(text, encoding='utf-8')
    print(f"      ✅ {len(text)} chars → {save_path.name}")
    return str(save_path)

# ── 主采集函数 ────────────────────────────────────────────────────────────────

# 千帆页面配置：(路径, 标签, 最小粒度, 是否有自定义日期)
# URL 探测日期：2026-03-28（通过侧边栏点击逐一确认）
ARK_PAGES = [
    # ── 交易数据 ──────────────────────────────────────────────
    ('/app-datacenter/business-overview', '成交分析',     'day',  True),
    ('/app-datacenter/business-account',  '账号分析',     'day',  True),
    ('/app-datacenter/business-refund',   '退款分析',     'day',  True),
    ('/app-datacenter/business-order',    '订单明细',     'day',  True),
    ('/app-datacenter/business-cps',      '买手分析',     'day',  True),
    # ── 流量 ─────────────────────────────────────────────────
    ('/app-datacenter/overview',          '数据总览',     'day',  True),
    ('/app-datacenter/flow-overview',     '流量数据',     'day',  True),
    # ── 商品 ─────────────────────────────────────────────────
    ('/app-datacenter/good-data',         '商品总览',     'day',  True),
    ('/app-datacenter/good-data/real-time',          '实时商品数据', 'day', True),
    ('/app-datacenter/good-data/category-analysis',  '商家类目',    'day', True),
    # ── 搜索 ─────────────────────────────────────────────────
    ('/app-datacenter/search-overview',        '搜索总览',   'day', True),
    ('/app-datacenter/search-overview/words',  '引流搜索词', 'day', True),
    # ── 笔记 ─────────────────────────────────────────────────
    ('/app-datacenter/note-data/goods',   '笔记数据',     'day',  True),
    ('/app-datacenter/note-cooperate',    '买手笔记',     'day',  True),
    ('/app-datacenter/note-blue-chain',   '笔记蓝链',     'day',  True),
    # ── 店铺 / 服务 ──────────────────────────────────────────
    ('/app-datacenter/homepage',          '店铺主页',     'day',  True),
    ('/app-datacenter/comment-overview',  '评价数据',     'day',  True),
    ('/app-datacenter/after-sale',        '售后数据',     'day',  True),
    ('/app-datacenter/logistics-data',    '物流数据',     'day',  True),
    ('/app-datacenter/customer-data',     '客服数据',     'week', True),
    ('/app-datacenter/group-chat',        '群聊数据',     'day',  True),
    ('/app-datacenter/live-goods',        '买手清单',     'day',  True),
    # ── 市场 ─────────────────────────────────────────────────
    ('/app-datacenter/market/note-rank',  '市场行情',     'day',  True),
    # ── 用户分析（快照，无日期筛选）──────────────────────────────
    # 人群分层 6tab×3subtab，由 collect_user_pages.mjs 处理
    ('/app-circle/user-data',             '人群分析',     'none', False),
    # AINRL 5tab×2subtab + 笔记详情，由 collect_user_pages.mjs 处理
    ('/app-promotion/user-assets',        'AINRL用户资产', 'none', False),
]

def run_historical(start_date: date, end_date: date) -> dict[str, Any]:
    """全量历史采集"""
    print(f"\n{'='*60}")
    print(f"历史数据采集  {start_date} → {end_date}")
    print(f"总天数: {(end_date - start_date).days + 1} 天")
    segments = date_segments(start_date, end_date, max_days=90)
    print(f"分段数: {len(segments)} 段（每段≤90天）")
    print(f"{'='*60}")

    # 找 ark tab ID（用 navigate 一次获取，之后复用）
    print("\n[1] 获取 Ark Tab ID...")
    nav = _nav('https://ark.xiaohongshu.com/app-datacenter/business-overview', 500)
    if not nav.get('tabId'):
        print("  ❌ 无法获取 ark tab，请确认 Chrome 已登录 ark.xiaohongshu.com")
        return {}
    ARK_TAB = nav['tabId']
    print(f"  ✅ ark tab_id = {ARK_TAB}")
    time.sleep(8)

    results: dict[str, Any] = {
        'start': str(start_date),
        'end': str(end_date),
        'segments': [f"{s[0]}~{s[1]}" for s in segments],
        'pages': {},
    }

    # 按页面分别采集各时间段
    print(f"\n[2] 千帆数据采集（{len(ARK_PAGES)} 个页面 × {len(segments)} 段）")
    for path, label, granularity, has_custom in ARK_PAGES:
        print(f"\n  ▶ {label}")
        results['pages'][label] = []

        if not has_custom:
            # 无日期筛选的页面（如人群分析）：只采集一次当前快照
            today_str = date.today().strftime('%Y-%m-%d')
            seg_path = collect_ark_page_snapshot(ARK_TAB, path, label, today_str)
            if seg_path:
                results['pages'][label].append({
                    'period': f"snapshot_{today_str}",
                    'file': seg_path,
                })
            time.sleep(2)
            continue

        for seg_start, seg_end in segments:
            seg_path = collect_ark_page_for_period(
                ARK_TAB, path, label,
                seg_start.strftime('%Y-%m-%d'),
                seg_end.strftime('%Y-%m-%d')
            )
            if seg_path:
                results['pages'][label].append({
                    'period': f"{seg_start}~{seg_end}",
                    'file': seg_path,
                })
            time.sleep(2)

    # 保存采集清单
    manifest_path = HIST_DIR / f"manifest_{start_date}_{end_date}.json"
    manifest_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"\n✅ 采集完成！清单保存至: {manifest_path}")
    print(f"   成功采集页面: {sum(len(v) for v in results['pages'].values())} 条记录")
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='XHS 历史数据全量采集')
    parser.add_argument('--start', default='2025-10-01', help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end',   default=date.today().strftime('%Y-%m-%d'), help='结束日期')
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    run_historical(start, end)
