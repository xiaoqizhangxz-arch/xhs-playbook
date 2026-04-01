"""
xhs_full_collector.py — XHS 全量数据采集器

采集来源：
  - creator.xiaohongshu.com  → 创作者指标（opencli CLI）
  - ark.xiaohongshu.com      → 千帆电商数据（AppleScript + DOM innerText）

使用方式：
  python3 -m revenue_os.acquisition.xhs_full_collector --mode full
  python3 -m revenue_os.acquisition.xhs_full_collector --mode daily
  python3 -m revenue_os.acquisition.xhs_full_collector --mode weekly
  python3 -m revenue_os.acquisition.xhs_full_collector --mode monthly

前提条件：
  - Chrome Tab: creator.xiaohongshu.com（已登录）
  - Chrome Tab: ark.xiaohongshu.com（已登录）
  - opencli daemon 运行中（opencli doctor 确认，Browser Bridge Connected）
  - Apple 事件 JS 权限已开启（Chrome 菜单→查看→开发者→允许 Apple 事件中的 JavaScript）

已知限制（2026-03-31 验证）：
  - 千帆图表全为 SVG 路径渲染（非 canvas，非 SVG text），DOM 无数值
  - 有数值的数据全在 innerText 里（成交/流量/商品/搜索等页面）
  - 人群画像（性别/年龄/地域）= 纯 SVG 图表，需手动从千帆导出 PDF
  - AINRL 用户资产漏斗在 /app-promotion/user-assets 的 innerText 可直接采集
  - 成交分析子 tab（载体/账号/人群构成）为懒加载 SVG，点击后仍无 DOM 数值
"""
from __future__ import annotations

import json
import subprocess
import time
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import REVENUE_OS_ROOT

# ── 路径配置 ─────────────────────────────────────────────────────────────────
SNAPSHOT_DIR    = REVENUE_OS_ROOT / "raw_data" / "creator_auto" / "snapshots"
CANVAS_DIR      = REVENUE_OS_ROOT / "raw_data" / "creator_auto" / "canvas_images"
ARK_DOM_DIR     = REVENUE_OS_ROOT / "raw_data" / "creator_auto" / "ark_dom"

for d in [SNAPSHOT_DIR, CANVAS_DIR, ARK_DOM_DIR]:
    d.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")

# ── Daemon 客户端（Node.js ESM，通过 subprocess 调用）────────────────────────
_DAEMON_SCRIPT = REVENUE_OS_ROOT / "scripts" / "revenue_os" / "acquisition" / "_daemon_exec.mjs"

def _write_daemon_script():
    """写出 Node.js ESM 帮助脚本（与 opencli daemon 通信）"""
    script = '''
import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { writeFileSync } from 'fs';

const [,, action, ...args] = process.argv;

async function exec(tabId, code) {
    return sendCommand('exec', { code, tabId });
}

async function main() {
    if (action === 'navigate') {
        const url = args[0];
        const timeout = parseInt(args[1] || '3000');
        const nav = await sendCommand('navigate', { url, timeout });
        process.stdout.write(JSON.stringify(nav));
    } else if (action === 'exec') {
        const tabId = parseInt(args[0]);
        const code = args.slice(1).join(' ');
        const result = await exec(tabId, code);
        process.stdout.write(JSON.stringify({ result }));
    } else if (action === 'screenshot') {
        const tabId = parseInt(args[0]);
        const result = await sendCommand('screenshot', { tabId, format: 'png' });
        const raw = typeof result === 'string' ? result : result?.data;
        process.stdout.write(raw || '');
    } else if (action === 'canvas') {
        // 提取页面所有 canvas 为 base64 PNG
        const tabId = parseInt(args[0]);
        const code = `(function(){
            var canvases = document.querySelectorAll('canvas');
            var results = {};
            canvases.forEach(function(c, i) {
                if (c.width > 100 && c.height > 100) {
                    try { results['canvas_'+i] = {
                        w: c.width, h: c.height,
                        data: c.toDataURL('image/png')
                    }; } catch(e) { results['canvas_'+i] = {error: e.message}; }
                }
            });
            return JSON.stringify(results);
        })()`;
        const r = await exec(tabId, code);
        const raw = typeof r === 'string' ? r : JSON.stringify(r);
        process.stdout.write(raw || '{}');
    }
}

main().catch(e => { process.stderr.write(e.message); process.exit(1); });
'''
    _DAEMON_SCRIPT.write_text(script, encoding='utf-8')

def _node_exec(action: str, *args: str, timeout: int = 30) -> str:
    """调用 Node.js daemon 帮助脚本"""
    if not _DAEMON_SCRIPT.exists():
        _write_daemon_script()
    result = subprocess.run(
        ['node', str(_DAEMON_SCRIPT), action, *args],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()

# ── AppleScript 辅助（用于 ark tab 导航，保持 session）───────────────────────
def _apples(script: str) -> str:
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

def _chrome_js(tab_n: int, js: str) -> str:
    script = f'tell application "Google Chrome"\nreturn execute tab {tab_n} of window 1 javascript {json.dumps(js)}\nend tell'
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=20)
    return r.stdout.strip()

def _find_ark_tab() -> int | None:
    """找 ark.xiaohongshu.com tab 编号"""
    r = _apples('''tell application "Google Chrome"
        repeat with i from 1 to count of tabs of window 1
            if URL of tab i of window 1 contains "ark.xiaohongshu.com" then
                return i as string
            end if
        end repeat
        return "0"
    end tell''')
    n = int(r.strip()) if r.strip().isdigit() else 0
    return n if n > 0 else None

def _nav_ark_tab(path: str, tab: int) -> None:
    """在已登录的 ark tab 里导航（保持 session）"""
    url = f"https://ark.xiaohongshu.com{path}"
    _apples(f'tell application "Google Chrome"\nset URL of tab {tab} of window 1 to "{url}"\nend tell')
    time.sleep(8)

def _read_ark_tab(tab: int) -> str:
    return _chrome_js(tab, 'document.body.innerText')

# ── 数据采集函数 ──────────────────────────────────────────────────────────────

def collect_creator_api(note_id: str | None = None) -> dict[str, Any]:
    """通过 opencli daemon 采集 creator API 数据"""
    print("  [creator API] note_detail_new...")
    nav_raw = _node_exec('navigate',
        'https://creator.xiaohongshu.com/new/home', '3000', timeout=15)
    try:
        nav = json.loads(nav_raw)
    except Exception:
        nav = {}
    tab_id = nav.get('tabId')
    if not tab_id:
        print("    ⚠️ navigate 失败，跳过 creator API")
        return {}

    time.sleep(10)

    js = """(async function(){
        var out = {};
        var apis = {
            note_detail_new: '/api/galaxy/creator/data/note_detail_new',
            personal_info: '/api/galaxy/creator/home/personal_info',
            latest_note: '/api/galaxy/creator/home/latest_note_data',
        };
        for (var key in apis) {
            try {
                var r = await fetch(apis[key], {credentials:'include'});
                out[key] = await r.json();
            } catch(e) { out[key] = {error: e.message}; }
        }
        return JSON.stringify(out);
    })()"""

    # 触发 async JS
    trigger = f"(function(){{window.__r=null;({js})().then(d=>{{window.__r=d;}}).catch(e=>{{window.__r='ERR:'+e.message;}});return 'ok';}})()"
    _node_exec('exec', str(tab_id), trigger, timeout=10)
    time.sleep(8)
    raw = _node_exec('exec', str(tab_id), 'window.__r||"null"', timeout=10)
    try:
        return json.loads(raw)
    except Exception:
        return {'raw': raw[:500]}

def collect_creator_note_detail(note_id: str, tab_id: int) -> dict[str, Any]:
    """采集单篇笔记数据 + Canvas 图表"""
    print(f"  [note-detail] {note_id}...")
    nav_raw = _node_exec('navigate',
        f'https://creator.xiaohongshu.com/statistics/note-detail?noteId={note_id}',
        '3000', timeout=15)
    try:
        nav = json.loads(nav_raw)
        tab = nav.get('tabId', tab_id)
    except Exception:
        tab = tab_id

    time.sleep(12)

    result: dict[str, Any] = {}

    # DOM 文本
    result['dom_text'] = _node_exec('exec', str(tab), 'document.body.innerText', timeout=10)

    # Canvas 图表
    canvas_tabs = ['观看来源', '观众画像']
    canvases: dict[str, str] = {}
    for tab_name in canvas_tabs:
        click_js = f"""(function(){{
            var all=Array.from(document.querySelectorAll('*'));
            var el=all.find(e=>e.childNodes.length<=2&&e.innerText&&e.innerText.trim()==='{tab_name}');
            if(el){{el.click();return 'ok';}} return 'nf';
        }})()"""
        _node_exec('exec', str(tab), click_js, timeout=10)
        time.sleep(6)

        canvas_raw = _node_exec('canvas', str(tab), timeout=15)
        try:
            canvas_data = json.loads(canvas_raw)
            for key, val in canvas_data.items():
                if isinstance(val, dict) and 'data' in val and val['data'].startswith('data:image'):
                    b64 = val['data'].replace('data:image/png;base64,', '')
                    save_path = CANVAS_DIR / f"{TODAY}_{note_id}_{tab_name.replace(' ','')}_{key}.png"
                    import base64
                    save_path.write_bytes(base64.b64decode(b64))
                    canvases[f"{tab_name}_{key}"] = str(save_path)
        except Exception as e:
            print(f"    ⚠️ canvas 提取失败: {e}")

    result['canvas_paths'] = canvases
    result['canvas_count'] = len(canvases)
    return result

def collect_ark_all(modes: list[str]) -> dict[str, Any]:
    """采集千帆所有数据页面"""
    ark_tab = _find_ark_tab()
    if not ark_tab:
        print("  ⚠️ 未找到 ark tab，跳过千帆采集")
        return {}

    # 先确认在 overview（已登录的基础页面）
    _apples(f'tell application "Google Chrome"\nset URL of tab {ark_tab} of window 1 to "https://ark.xiaohongshu.com/app-datacenter/overview"\nend tell')
    time.sleep(8)

    # 时间窗口配置
    # URL 全量探测日期：2026-03-28（侧边栏点击确认）
    time_windows = {
        'daily': [
            '/app-datacenter/overview',
            '/app-datacenter/note-data/goods',
        ],
        'weekly': [
            '/app-datacenter/overview',
            '/app-datacenter/flow-overview',
            '/app-datacenter/good-data',
            '/app-datacenter/good-data/real-time',
            '/app-datacenter/good-data/category-analysis',
            '/app-datacenter/business-overview',
            '/app-datacenter/search-overview',
            '/app-datacenter/search-overview/words',
            '/app-datacenter/note-data/goods',
            '/app-datacenter/note-cooperate',
            '/app-datacenter/comment-overview',
            '/app-datacenter/market/note-rank',
        ],
        'monthly': [
            '/app-datacenter/overview',
            '/app-datacenter/flow-overview',
            '/app-datacenter/good-data',
            '/app-datacenter/good-data/real-time',
            '/app-datacenter/good-data/category-analysis',
            '/app-datacenter/business-overview',
            '/app-datacenter/business-account',
            '/app-datacenter/business-refund',
            '/app-datacenter/business-cps',
            '/app-datacenter/search-overview',
            '/app-datacenter/search-overview/words',
            '/app-datacenter/note-data/goods',
            '/app-datacenter/note-cooperate',
            '/app-datacenter/note-blue-chain',
            '/app-datacenter/comment-overview',
            '/app-datacenter/after-sale',
            '/app-datacenter/customer-data',
            '/app-datacenter/logistics-data',
            '/app-datacenter/group-chat',
            '/app-datacenter/live-goods',
            '/app-datacenter/homepage',
            '/app-datacenter/market/note-rank',
        ],
        'full': [
            '/app-datacenter/overview',
            '/app-datacenter/flow-overview',
            '/app-datacenter/good-data',
            '/app-datacenter/good-data/real-time',
            '/app-datacenter/good-data/category-analysis',
            '/app-datacenter/business-overview',
            '/app-datacenter/business-account',
            '/app-datacenter/business-refund',
            '/app-datacenter/business-cps',
            '/app-datacenter/business-order',
            '/app-datacenter/search-overview',
            '/app-datacenter/search-overview/words',
            '/app-datacenter/note-data/goods',
            '/app-datacenter/note-cooperate',
            '/app-datacenter/note-blue-chain',
            '/app-datacenter/comment-overview',
            '/app-datacenter/after-sale',
            '/app-datacenter/customer-data',
            '/app-datacenter/logistics-data',
            '/app-datacenter/group-chat',
            '/app-datacenter/live-goods',
            '/app-datacenter/homepage',
            '/app-datacenter/market/note-rank',
        ],
    }

    # 路径→标签映射（全量，2026-03-28 确认）
    LABEL_MAP = {
        '/app-datacenter/overview':                  '数据总览',
        '/app-datacenter/flow-overview':             '流量数据',
        '/app-datacenter/good-data':                 '商品总览',
        '/app-datacenter/good-data/real-time':       '实时商品数据',
        '/app-datacenter/good-data/category-analysis': '商家类目',
        '/app-datacenter/business-overview':         '成交分析',
        '/app-datacenter/business-account':          '账号分析',
        '/app-datacenter/business-refund':           '退款分析',
        '/app-datacenter/business-cps':              '买手分析',
        '/app-datacenter/business-order':            '订单明细',
        '/app-datacenter/search-overview':           '搜索总览',
        '/app-datacenter/search-overview/words':     '引流搜索词',
        '/app-datacenter/note-data/goods':           '笔记数据',
        '/app-datacenter/note-cooperate':            '买手笔记',
        '/app-datacenter/note-blue-chain':           '笔记蓝链',
        '/app-datacenter/comment-overview':          '评价数据',
        '/app-datacenter/after-sale':                '售后数据',
        '/app-datacenter/customer-data':             '客服数据',
        '/app-datacenter/logistics-data':            '物流数据',
        '/app-datacenter/group-chat':                '群聊数据',
        '/app-datacenter/live-goods':                '买手清单',
        '/app-datacenter/homepage':                  '店铺主页',
        '/app-datacenter/market/note-rank':          '市场行情',
        '/app-datacenter/homepage': '店铺主页',
        '/app-datacenter/market/note-rank': '市场行情',
    }

    # 合并去重要采集的页面
    pages_to_collect: list[str] = []
    for mode in modes:
        for p in time_windows.get(mode, []):
            if p not in pages_to_collect:
                pages_to_collect.append(p)

    collected: dict[str, str] = {}
    for path in pages_to_collect:
        label = LABEL_MAP.get(path, path.split('/')[-1])
        print(f"  [ark] {label}...")
        _nav_ark_tab(path, ark_tab)
        text = _read_ark_tab(ark_tab)
        if len(text) > 200:
            save_path = ARK_DOM_DIR / f"{TODAY}_{label}.txt"
            save_path.write_text(text, encoding='utf-8')
            collected[label] = str(save_path)
            print(f"    ✅ {len(text)} chars")
        else:
            print(f"    ⚠️ 内容过短（{len(text)} chars），可能需要重试")
        time.sleep(1)

    return collected

def run_collection(mode: str = 'daily') -> dict[str, Any]:
    """主采集函数"""
    print(f"\n{'='*60}")
    print(f"XHS 数据采集  mode={mode}  date={TODAY}")
    print(f"{'='*60}")

    snapshot: dict[str, Any] = {
        'snapshot_date': TODAY,
        'collection_mode': mode,
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'sources': {},
    }

    # 1. Creator API
    print("\n[1] Creator API 采集")
    creator_data = collect_creator_api()
    if creator_data:
        snapshot['creator_api'] = creator_data
        snapshot['sources']['creator_api'] = 'ok'
    else:
        snapshot['sources']['creator_api'] = 'failed'

    # 2. 千帆 DOM
    print("\n[2] 千帆 Ark DOM 采集")
    modes_for_ark = [mode] if mode != 'full' else ['full']
    ark_data = collect_ark_all(modes_for_ark)
    snapshot['ark_pages'] = ark_data
    snapshot['sources']['ark'] = f"{len(ark_data)} pages"

    # 3. 保存快照
    save_path = SNAPSHOT_DIR / f"snapshot_{TODAY}_{mode}.json"
    save_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n✅ 快照保存：{save_path}")
    print(f"   Creator API: {snapshot['sources'].get('creator_api')}")
    print(f"   Ark 页面: {snapshot['sources'].get('ark')}")

    return snapshot

# ── CLI 入口 ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='XHS 数据全量采集')
    parser.add_argument('--mode', choices=['full', 'daily', 'weekly', 'monthly'],
                        default='daily', help='采集模式')
    parser.add_argument('--note-id', default=None, help='指定采集单篇笔记详情')
    args = parser.parse_args()
    run_collection(mode=args.mode)
