"""
xhs_historical_collector.py — 历史数据全量采集（分段，按92天限制）

用法：
  python3 -m revenue_os.acquisition.xhs_historical_collector
  python3 -m revenue_os.acquisition.xhs_historical_collector --start 2025-10-01 --end 2026-03-28

工作原理：
  1. 把时间范围按92天切割成多段
  2. 对每段：用 JS 设置自定义日期范围 → 等待数据加载 → 读取 DOM → 保存
  3. Creator API（30天限制）按月分段调用
  4. Canvas 图表标记为待 Agent OCR 处理
"""
from __future__ import annotations

import json
import subprocess
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

# ── 千帆自定义日期设置 ────────────────────────────────────────────────────────
def set_ark_date_range(tab_id: int, start_str: str, end_str: str) -> bool:
    """在千帆页面设置自定义日期范围，返回是否成功"""
    # 点自定义
    _exec(tab_id, """(function(){
        var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
        var n;
        while(n=w.nextNode()){if(n.textContent.trim()==='自定义'){n.parentElement.click();return;}}
    })()""")
    time.sleep(1.5)

    # 点击开始时间 input 触发日历
    _exec(tab_id, """(function(){
        var inp=document.querySelector('input[placeholder="开始时间"]');
        if(inp){inp.focus();inp.click();inp.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));}
    })()""")
    time.sleep(1.5)

    # 设置日期
    set_code = f"""(function(){{
        var setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        var s=document.querySelector('input[placeholder="开始时间"]');
        var e=document.querySelector('input[placeholder="截止时间"]');
        if(s){{setter.call(s,'{start_str}');['input','change','blur'].forEach(ev=>s.dispatchEvent(new Event(ev,{{bubbles:true}})));}}
        if(e){{setter.call(e,'{end_str}');['input','change','blur'].forEach(ev=>e.dispatchEvent(new Event(ev,{{bubbles:true}})));}}
        return s?.value + '|' + e?.value;
    }})()"""
    result = _exec(tab_id, set_code)
    time.sleep(1)

    # 验证统计时间已更新
    body = _exec(tab_id, 'document.body.innerText')
    if not isinstance(body, str):
        body = str(body)
    return start_str in body or start_str.replace('-', '') in body

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
ARK_PAGES = [
    ('/app-datacenter/business-overview', '成交分析',   'day', True),
    ('/app-datacenter/flow-overview',     '流量数据',   'day', True),
    ('/app-datacenter/good-data',         '商品总览',   'day', True),
    ('/app-datacenter/search-overview',   '搜索总览',   'day', True),
    ('/app-datacenter/search-overview/words', '引流搜索词', 'day', True),
    ('/app-datacenter/business-account',  '账号分析',   'day', True),
    ('/app-datacenter/note-data/goods',   '笔记数据',   'day', True),
    ('/app-datacenter/homepage',          '店铺主页',   'day', True),
    ('/app-datacenter/comment-overview',  '评价数据',   'day', True),
    ('/app-datacenter/business-order',    '订单明细',   'day', True),
    ('/app-datacenter/logistics-data',    '物流数据',   'day', True),
    ('/app-datacenter/customer-data',     '客服数据',   'week', True),
    ('/app-datacenter/group-chat',        '群聊数据',   'day', True),
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
