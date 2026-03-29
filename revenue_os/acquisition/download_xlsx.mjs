/**
 * download_xlsx.mjs — 千帆 ARK XLSX 自动下载
 *
 * 机制：导航到数据页 → 点击"下载数据"按钮 → 等待浏览器下载到 ~/Downloads → 移入 source_auto/
 * 验证：2026-03-28 dry-run 14/14 页面按钮全部可达
 *
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 时间窗口：⚠️ 当前下载页面默认时间窗口（待实现日期设置）
 *
 * 千帆 ARK 数据页有时间切换 tab（近7日/近30日/自定义）。
 * 当前脚本直接点击"下载数据"，下载的是页面当前显示的时间范围。
 *
 * 待实现：在下载前先调用 setDateWindow(tabId, mode)：
 *   - mode='30d' → 点击"近30日" tab → 等待刷新 → 点下载
 *   - mode='custom' → 设置开始/结束日期 → 点下载
 *   跨月日历问题同 xhs_historical_collector.py（需月份导航逻辑）
 *
 * 临时方案：在浏览器里手动切换时间窗口后运行此脚本
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *
 * 有下载按钮的14个页面（source_auto/ 目标目录）：
 *   成交分析/流量数据/商品总览/商家类目/搜索总览/引流搜索词
 *   笔记数据/买手笔记/账号分析/退款分析/订单明细/评价数据/店铺主页/商品管理
 *
 * 无下载按钮（只能 DOM 采集）：
 *   实时商品数据/售后数据/物流数据/客服数据/群聊数据/市场行情
 *
 * 用法：
 *   node download_xlsx.mjs                               # 全量下载（页面默认时间窗口）
 *   node download_xlsx.mjs --window=30d                  # 先切换到近30日再下载
 *   node download_xlsx.mjs --window=7d                   # 先切换到近7日再下载
 *   node download_xlsx.mjs --window=custom:2026-01-01:2026-03-28  # 自定义跨月日期
 *   node download_xlsx.mjs --pages=成交分析,流量数据        # 指定页面
 *   node download_xlsx.mjs --dry-run                     # 验证按钮可达，不实际下载
 */

import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { readdirSync, statSync, mkdirSync, copyFileSync, existsSync } from 'fs';
import { join, basename, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const NODE_ROOT = join(__dirname, '../../../runtime/revenue_os/.tooling/creator_capture/node');
const PLAYWRIGHT_MODULE = join(NODE_ROOT, 'node_modules/@playwright/test');
const DOWNLOADER_JS = join(__dirname, '_ark_xlsx_downloader.js');

// ── Playwright subprocess: handles custom date range download ─────────────────
async function playwrightDownload(pageUrl, btnText, destDir, windowArg) {
    const cookiesPath = join(NODE_ROOT, '_tmp_cookies.json');
    try {
        // Dump Chrome cookies via shell (handles paths with spaces)
        const pyScript = join(NODE_ROOT, '_cookie_dump.py');
        const { writeFileSync: wfs } = await import('fs');
        wfs(pyScript, `
import json, browser_cookie3
from pathlib import Path
cookies = []
for c in browser_cookie3.chrome(domain_name='xiaohongshu.com'):
    cookies.append({'name':c.name,'value':c.value,'domain':c.domain,
        'path':c.path or '/','expires':float(c.expires) if c.expires else -1,
        'httpOnly':bool((getattr(c,'_rest',{}) or {}).get('HttpOnly')),
        'secure':bool(c.secure),'sameSite':'Lax'})
Path('${cookiesPath.replace(/'/g, "\\'")}').write_text(json.dumps(cookies))
`);
        // Use known absolute path to venv python (avoids path-with-spaces issues)
        const venvPython = join(NODE_ROOT, '..', 'py', 'venv', 'bin', 'python');
        execFileSync('/bin/sh', ['-c', `"${venvPython}" "${pyScript}"`],
            { stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 });
    } catch(e) {
        return { ok: false, error: 'cookie dump failed: ' + (e.stderr?.toString().slice(-100) || e.message.slice(0, 100)) };
    }

    try {
        const result = execFileSync('/bin/sh', ['-c',
            `COOKIES_JSON="${cookiesPath}" PLAYWRIGHT_MODULE="${PLAYWRIGHT_MODULE}" PLAYWRIGHT_CHANNEL="" ` +
            `node "${DOWNLOADER_JS}" "${pageUrl}" "${btnText}" "${destDir}" "${windowArg || ''}"`
        ], { cwd: NODE_ROOT, timeout: 90000, stdio: ['pipe', 'pipe', 'pipe'] });
        return JSON.parse(result.toString().trim() || '{}');
    } catch(e) {
        const stderr = e.stderr ? e.stderr.toString().slice(-300) : '';
        const stdout = e.stdout ? e.stdout.toString().trim() : '';
        try { return JSON.parse(stdout || '{}'); } catch(_) {}
        return { ok: false, error: stderr || e.message.slice(0, 150) };
    }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── 配置 ─────────────────────────────────────────────────────────────────────
const DOWNLOADS_DIR = `${process.env.HOME}/Downloads`;
const DEST_DIR = `${process.env.HOME}/Library/Mobile Documents/com~apple~CloudDocs/Thoth_Academy_Obsidian/08_Le_Fond_Bridge/Business Library/raw_data/source_auto`;
const BASE_URL = 'https://ark.xiaohongshu.com';

const DRY_RUN = process.argv.includes('--dry-run');
const PAGES_FILTER = process.argv.find(a => a.startsWith('--pages='))?.slice(8)?.split(',') || null;
// 时间窗口: --window 30d | 7d | custom:2026-01-01:2026-02-28
const WINDOW_ARG = process.argv.find(a => a.startsWith('--window='))?.slice(9) || null;

// ── 页面配置 ─────────────────────────────────────────────────────────────────
// 格式: { path, label, btnText, destDir }
// 验证日期: 2026-03-28
const DOWNLOAD_PAGES = [
    // 交易数据
    { path: '/app-datacenter/business-overview', label: '成交分析',   btnText: '下载数据', destDir: '商家成交' },
    { path: '/app-datacenter/flow-overview',     label: '流量数据',   btnText: '下载数据', destDir: '商家流量' },
    { path: '/app-datacenter/good-data',         label: '商品总览',   btnText: '下载数据', destDir: '商品明细' },
    { path: '/app-datacenter/good-data/category-analysis', label: '商家类目', btnText: '下载数据', destDir: '商家类目' },
    { path: '/app-datacenter/search-overview',   label: '搜索总览',   btnText: '下载数据', destDir: '搜索' },
    { path: '/app-datacenter/search-overview/words', label: '引流搜索词', btnText: '下载数据', destDir: '搜索' },
    { path: '/app-datacenter/note-data/goods',   label: '笔记数据',   btnText: '下载数据', destDir: 'posts_metrics' },
    { path: '/app-datacenter/note-cooperate',    label: '买手笔记',   btnText: '下载数据', destDir: '买手笔记' },
    { path: '/app-datacenter/business-account',  label: '账号分析',   btnText: '下载数据', destDir: '账号总览' },
    { path: '/app-datacenter/business-refund',   label: '退款分析',   btnText: '下载数据', destDir: '退款分析' },
    { path: '/app-datacenter/business-order',    label: '订单明细',   btnText: '下载数据', destDir: '订单明细' },
    { path: '/app-datacenter/comment-overview',  label: '评价数据',   btnText: '下载数据', destDir: '评价' },
    { path: '/app-datacenter/homepage',          label: '店铺主页',   btnText: '下载数据', destDir: '店铺页' },
    // 管理类
    { path: '/app-item/list/shelf',              label: '商品管理',   btnText: '导出查询结果', destDir: '售卖中商品' },
];

// ── 日期设置函数（千帆 ARK 通用）─────────────────────────────────────────────
// 月份文字选择器：.css-vmmof7 → "2026 年" / "03 月"
// 前箭头(←单月): .css-cvpy5t  后箭头(→单月): .css-fvvjfw
// 日期格子: .calendar-dayCell

async function execOnTab(code) {
    return sendCommand('exec', { code, tabId: TAB });
}

async function getDisplayedMonths() {
    const texts = await execOnTab([
        '(function(){',
        '  return Array.from(document.querySelectorAll(".css-vmmof7"))',
        '    .filter(function(el){ return el.getBoundingClientRect().height > 0; })',
        '    .map(function(el){ return el.innerText.trim(); });',
        '})()'
    ].join(''));
    const arr = Array.isArray(texts) ? texts : JSON.parse(texts || '[]');
    const months = [];
    for(let i = 0; i < arr.length - 1; i++) {
        const yM = arr[i].match(/(\d{4})/);
        const mM = arr[i+1].match(/(\d{1,2})/);
        if(yM && mM) months.push({ year: parseInt(yM[1]), month: parseInt(mM[1]) });
    }
    return months;
}

async function navigateToMonth(targetYear, targetMonth) {
    for(let a = 0; a < 36; a++) {
        const months = await getDisplayedMonths();
        if(!months.length) break;
        const left = months[0];
        const diff = (left.year - targetYear) * 12 + (left.month - targetMonth);
        if(diff === 0) return true;

        const svgs = await execOnTab([
            '(function(){',
            '  return Array.from(document.querySelectorAll(".css-7ll3nl")).map(function(svg){',
            '    var r=svg.getBoundingClientRect();',
            '    return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),cls:svg.className.baseVal};',
            '  });',
            '})()'
        ].join(''));
        const svgArr = Array.isArray(svgs) ? svgs : JSON.parse(svgs || '[]');
        if(diff > 0) {
            const prev = svgArr.find(function(s){ return s.cls.indexOf('css-cvpy5t') > -1; });
            if(prev) await execOnTab([
                '(function(){',
                '  var svg=Array.from(document.querySelectorAll(".css-7ll3nl")).find(function(s){return s.className.baseVal.indexOf("css-cvpy5t")>-1;});',
                '  if(!svg) return;',
                '  var r=svg.getBoundingClientRect();',
                '  var opts={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};',
                '  svg.dispatchEvent(new PointerEvent("pointerdown",opts));',
                '  svg.dispatchEvent(new MouseEvent("mousedown",opts));',
                '  svg.dispatchEvent(new PointerEvent("pointerup",opts));',
                '  svg.dispatchEvent(new MouseEvent("mouseup",opts));',
                '  svg.dispatchEvent(new MouseEvent("click",opts));',
                '})()'
            ].join(''));
        } else {
            const next = svgArr.find(function(s){ return s.cls.indexOf('css-fvvjfw') > -1; });
            if(next) await execOnTab([
                '(function(){',
                '  var svg=Array.from(document.querySelectorAll(".css-7ll3nl")).find(function(s){return s.className.baseVal.indexOf("css-fvvjfw")>-1;});',
                '  if(!svg) return;',
                '  var r=svg.getBoundingClientRect();',
                '  var opts={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};',
                '  svg.dispatchEvent(new PointerEvent("pointerdown",opts));',
                '  svg.dispatchEvent(new MouseEvent("mousedown",opts));',
                '  svg.dispatchEvent(new PointerEvent("pointerup",opts));',
                '  svg.dispatchEvent(new MouseEvent("mouseup",opts));',
                '  svg.dispatchEvent(new MouseEvent("click",opts));',
                '})()'
            ].join(''));
        }
        await sleep(450);
    }
    return false;
}

async function clickDayCell(day, inLeftCalendar) {
    const cells = await execOnTab([
        '(function(){',
        '  return Array.from(document.querySelectorAll(".calendar-dayCell")).map(function(c){',
        '    var r=c.getBoundingClientRect();',
        '    return {text:c.innerText.trim(),x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),left:Math.round(r.x)};',
        '  });',
        '})()'
    ].join(''));
    const cellArr = Array.isArray(cells) ? cells : JSON.parse(cells || '[]');
    if(!cellArr.length) return false;
    // Find the separator between left/right calendars by detecting the largest gap in x values
    var uniqueXs = cellArr.map(function(c){ return c.left; })
        .filter(function(x,i,a){ return a.indexOf(x)===i; })
        .sort(function(a,b){ return a-b; });
    var maxGap = 0, midX = uniqueXs[Math.floor(uniqueXs.length/2)];
    for(var gi=0; gi<uniqueXs.length-1; gi++) {
        var gap = uniqueXs[gi+1] - uniqueXs[gi];
        if(gap > maxGap) { maxGap = gap; midX = (uniqueXs[gi] + uniqueXs[gi+1]) / 2; }
    }
    var target = cellArr.find(function(c){
        return c.text === String(day) && (inLeftCalendar ? c.left < midX : c.left >= midX);
    });
    if(target) {
        const cx = target.x, cy = target.y;
        await execOnTab([
            `(function(){`,
            `  var opts={bubbles:true,cancelable:true,view:window,clientX:${cx},clientY:${cy}};`,
            `  var el=document.elementFromPoint(${cx},${cy});`,
            `  if(!el){`,
            `    var cells=Array.from(document.querySelectorAll(".calendar-dayCell"));`,
            `    el=cells.find(function(c){return c.innerText.trim()==="${target.text}";});`,
            `  }`,
            `  if(el){`,
            `    el.dispatchEvent(new PointerEvent("pointerdown",opts));`,
            `    el.dispatchEvent(new MouseEvent("mousedown",opts));`,
            `    el.dispatchEvent(new PointerEvent("pointerup",opts));`,
            `    el.dispatchEvent(new MouseEvent("mouseup",opts));`,
            `    el.dispatchEvent(new MouseEvent("click",opts));`,
            `  }`,
            `})()`
        ].join(''));
        return true;
    }
    return false;
}

async function clickTimeTabText(text) {
    return execOnTab([
        `(function(){`,
        `  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); var n;`,
        `  while(n=w.nextNode()){`,
        `    if(n.textContent.trim()==="${text}"&&n.parentElement.getBoundingClientRect().height>0){`,
        `      n.parentElement.click(); return true;`,
        `    }`,
        `  }`,
        `  return false;`,
        `})()`
    ].join(''));
}

/**
 * 设置页面时间窗口后下载
 * windowArg: '30d' | '7d' | '1d' | 'custom:YYYY-MM-DD:YYYY-MM-DD' | null
 */
async function applyTimeWindow(windowArg) {
    if(!windowArg) return { ok: true, note: 'no window, using page default' };
    const tabMap = { '1d': '近1日', '7d': '近7日', '30d': '近30日' };
    if(tabMap[windowArg]) {
        await clickTimeTabText(tabMap[windowArg]);
        await sleep(2500);
        return { ok: true, note: `clicked ${tabMap[windowArg]}` };
    }
    if(windowArg.startsWith('custom:')) {
        const parts = windowArg.split(':');
        if(parts.length !== 3) return { ok: false, error: 'invalid custom format, use custom:YYYY-MM-DD:YYYY-MM-DD' };
        const [, startDate, endDate] = parts;
        const [sy, sm, sd] = startDate.split('-').map(Number);
        const [ey, em, ed] = endDate.split('-').map(Number);

        await clickTimeTabText('自定义');
        await sleep(1200);

        // Open start input to trigger calendar
        await execOnTab([
            '(function(){',
            '  var inp=document.querySelector("input[placeholder=\'开始时间\']");',
            '  if(inp){inp.focus();inp.click();}',
            '})()'
        ].join(''));
        await sleep(1200);

        // Navigate to start month
        const navOk = await navigateToMonth(sy, sm);
        if(!navOk) return { ok: false, error: `could not navigate to ${sy}/${sm}` };

        // Click start day
        const r1 = await clickDayCell(sd, true);
        if(!r1) return { ok: false, error: `start day ${sd} not found` };
        await sleep(600);

        // Click end day — navigate so end month appears in right calendar
        // Strategy: navigate left calendar to (endMonth - 1) so right = endMonth
        const endTargetLeftYear = (em > 1) ? ey : ey - 1;
        const endTargetLeftMonth = (em > 1) ? em - 1 : 12;
        await navigateToMonth(endTargetLeftYear, endTargetLeftMonth);
        const months2 = await getDisplayedMonths();
        // end month should now be in right calendar (months2[1])
        const endLeft2 = months2[0] && months2[0].year === ey && months2[0].month === em;
        const r2 = await clickDayCell(ed, endLeft2);
        if(!r2) return { ok: false, error: `end day ${ed} not found in calendar (months: ${JSON.stringify(months2)})` };
        await sleep(2500);

        // Close calendar (press Escape / click body) and wait for data reload
        await execOnTab('document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))');
        await sleep(500);
        await execOnTab('document.body.click()');
        await sleep(3000); // wait for data refresh

        // Verify
        const body = await execOnTab('document.body.innerText');
        const bodyStr = typeof body === 'string' ? body : JSON.stringify(body);
        const m = bodyStr.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
        const statsTime = m ? m[0] : '';
        const expected = `${startDate}~${endDate}`;
        console.log(`  📅 验证: expected=${expected}, got=${statsTime}`);
        const verified = statsTime === expected;
        return { ok: verified, statsTime, expected,
                 note: verified ? `统计时间: ${statsTime}` : null,
                 error: verified ? null : `日期验证失败: expected ${expected}, got ${statsTime||'(empty)'}` };
    }
    return { ok: false, error: 'unknown window: ' + windowArg };
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────
let TAB = null;

async function getTab() {
    if (TAB) {
        try {
            const url = await sendCommand('exec', { code: 'location.href', tabId: TAB });
            if (url && url.includes('ark.xiaohongshu.com') && !url.includes('login')) return TAB;
        } catch(e) {}
    }
    const nav = await sendCommand('navigate', { url: `${BASE_URL}/app-datacenter/business-overview`, timeout: 500 });
    TAB = nav.tabId;
    await sleep(8000);
    const url = await sendCommand('exec', { code: 'location.href', tabId: TAB });
    if (url.includes('login')) throw new Error('未登录千帆，请先在 Chrome 中登录 ark.xiaohongshu.com');
    return TAB;
}

async function exec(code) {
    const tabId = await getTab();
    return sendCommand('exec', { code, tabId });
}

// 记录下载前的 Downloads 目录状态
function snapshotDownloads() {
    try {
        return new Set(readdirSync(DOWNLOADS_DIR).map(f => join(DOWNLOADS_DIR, f)));
    } catch(e) { return new Set(); }
}

// 等待新的 xlsx/csv 文件出现
async function waitForNewFile(before, timeoutMs = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        await sleep(500);
        const after = readdirSync(DOWNLOADS_DIR);
        for (const f of after) {
            const fullPath = join(DOWNLOADS_DIR, f);
            if (!before.has(fullPath) && (f.endsWith('.xlsx') || f.endsWith('.csv') || f.endsWith('.xls'))) {
                // 等待文件写完（大小稳定）
                await sleep(1000);
                return fullPath;
            }
        }
    }
    return null;
}

// 移动文件到 source_auto 对应目录
function moveToSourceAuto(srcPath, destDirName) {
    const destDir = join(DEST_DIR, destDirName);
    mkdirSync(destDir, { recursive: true });
    const destPath = join(destDir, basename(srcPath));
    if (!DRY_RUN) {
        copyFileSync(srcPath, destPath);
    }
    return destPath;
}

// ── 日期分段工具 ──────────────────────────────────────────────────────────────
// 千帆范围选择器每次只能在不导航的情况下选定≤2个月内的日期
// 超过2个月的范围自动切分为 ≤55天 的段（确保始终在同月或相邻月内）
function splitDateRange(startStr, endStr, maxDays = 55) {
    const segments = [];
    let cur = new Date(startStr + 'T00:00:00');
    const end = new Date(endStr + 'T00:00:00');
    while(cur <= end) {
        const segEnd = new Date(cur);
        segEnd.setDate(segEnd.getDate() + maxDays - 1);
        if(segEnd > end) segEnd.setTime(end.getTime());
        const fmt = d => d.toISOString().slice(0, 10);
        segments.push({ start: fmt(cur), end: fmt(segEnd) });
        cur = new Date(segEnd);
        cur.setDate(cur.getDate() + 1);
    }
    return segments;
}

// ── 主流程 ────────────────────────────────────────────────────────────────────
console.log(`\n${'='.repeat(60)}`);
console.log(`千帆 XLSX 下载  ${DRY_RUN ? '[DRY RUN]' : ''}`);
console.log(`目标: ${DEST_DIR}`);
console.log(`${'='.repeat(60)}\n`);

await getTab();

const pages = PAGES_FILTER
    ? DOWNLOAD_PAGES.filter(p => PAGES_FILTER.includes(p.label))
    : DOWNLOAD_PAGES;

const results = [];

for (const page of pages) {
    console.log(`▶ ${page.label} (${page.path})`);

    // 导航到页面
    await sendCommand('navigate', { url: `${BASE_URL}${page.path}`, tabId: TAB, timeout: 500 });
    await sleep(5000);

    const currentUrl = await sendCommand('exec', { code: 'location.href', tabId: TAB });
    if (currentUrl.includes('login')) {
        console.log('  ❌ 登录失效，跳过');
        results.push({ label: page.label, status: 'skip_login' });
        continue;
    }

    // 检查下载按钮
    const btnExists = await sendCommand('exec', { code: [
        '(function(){',
        '  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);',
        '  var n;',
        '  while(n=w.nextNode()){',
        `    if(n.textContent.trim()==="${page.btnText}"&&n.parentElement.getBoundingClientRect().height>0) return true;`,
        '  }',
        '  return false;',
        '})()'
    ].join(''), tabId: TAB });

    if (!btnExists) {
        console.log(`  ⚠️ 未找到"${page.btnText}"按钮，跳过`);
        results.push({ label: page.label, status: 'no_btn' });
        continue;
    }

    if (DRY_RUN) {
        console.log(`  ✅ [DRY RUN] 找到按钮"${page.btnText}"${WINDOW_ARG ? '  window=' + WINDOW_ARG : ''}`);
        results.push({ label: page.label, status: 'dry_run' });
        continue;
    }

    // 自定义日期范围：playwright 全流程，自动分段（≤55天/段）
    if (WINDOW_ARG && WINDOW_ARG.startsWith('custom:') && page.btnText === '下载数据') {
        const parts = WINDOW_ARG.split(':');
        if (parts.length !== 3) {
            console.log(`  ❌ 格式错误: 应为 custom:YYYY-MM-DD:YYYY-MM-DD`);
            results.push({ label: page.label, status: 'error' });
            continue;
        }
        const [, rangeStart, rangeEnd] = parts;
        const segments = splitDateRange(rangeStart, rangeEnd);
        console.log(`  📅 自定义范围 ${rangeStart}~${rangeEnd}，分${segments.length}段`);

        const fullDestDir = join(DEST_DIR, page.destDir);
        mkdirSync(fullDestDir, { recursive: true });
        let segOk = 0;
        for (const seg of segments) {
            const segWindow = `custom:${seg.start}:${seg.end}`;
            console.log(`  🔄 [${seg.start}~${seg.end}] playwright 下载...`);
            const plResult = await playwrightDownload(
                `${BASE_URL}${page.path}`, page.btnText, fullDestDir, segWindow
            );
            if (plResult.ok) {
                console.log(`  ✅ ${plResult.file}`);
                segOk++;
            } else {
                console.log(`  ⚠️ 失败: ${plResult.error}`);
            }
            await sleep(1000);
        }
        results.push({ label: page.label, status: segOk === segments.length ? 'ok' : 'partial',
                        segments: segments.length, downloaded: segOk });
        continue;
    }

    // 简单时间 tab 或无时间设置：browser bridge 方式
    if (WINDOW_ARG && !WINDOW_ARG.startsWith('custom:') && page.btnText === '下载数据') {
        const wResult = await applyTimeWindow(WINDOW_ARG);
        if (!wResult.ok) {
            console.log(`  ⚠️ 时间窗口设置失败: ${wResult.error || WINDOW_ARG}，使用页面默认`);
        } else {
            console.log(`  📅 时间窗口: ${wResult.note || wResult.statsTime || WINDOW_ARG}`);
        }
    }

    // 记录下载前状态
    const before = snapshotDownloads();

    // 点击下载按钮
    await sendCommand('exec', { code: [
        '(function(){',
        '  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);',
        '  var n;',
        '  while(n=w.nextNode()){',
        `    if(n.textContent.trim()==="${page.btnText}"&&n.parentElement.getBoundingClientRect().height>0){`,
        '      n.parentElement.click();return "clicked";',
        '    }',
        '  }',
        '  return "not found";',
        '})()'
    ].join(''), tabId: TAB });

    console.log(`  🔄 等待下载...`);
    const newFile = await waitForNewFile(before, 20000);

    if (!newFile) {
        console.log('  ❌ 下载超时（20s）');
        results.push({ label: page.label, status: 'timeout' });
        continue;
    }

    console.log(`  ⬇️  下载完成: ${basename(newFile)}`);

    // 移动到 source_auto
    const destPath = moveToSourceAuto(newFile, page.destDir);
    console.log(`  ✅ 保存至: source_auto/${page.destDir}/${basename(newFile)}`);
    results.push({ label: page.label, status: 'ok', file: basename(newFile), dest: destPath });

    await sleep(2000); // 每次下载间隔
}

// ── 汇总 ─────────────────────────────────────────────────────────────────────
console.log(`\n${'='.repeat(60)}`);
console.log('下载汇总:');
const ok = results.filter(r => r.status === 'ok');
const skip = results.filter(r => r.status !== 'ok');
console.log(`  ✅ 成功: ${ok.length}/${results.length}`);
ok.forEach(r => console.log(`     ${r.label}: ${r.file}`));
if (skip.length > 0) {
    console.log(`  ⚠️ 跳过/失败:`);
    skip.forEach(r => console.log(`     ${r.label}: ${r.status}`));
}
